import os
import time
import wandb
import torch
import shutil
import cld3
import fire
import logging
import webdataset as wds
from img2dataset import download
from collections import Counter
from models import get_model
from utils import (
    convert_to_image_url_text_parquet,
    get_filtered_ngrams,
    get_before_after_text,
    load_perplexity_language_model,
    get_stats_table,
)


def run_pipeline(
    filename=None,
    convert=True,
    download_imgs=True,
    converted_filename=None,
    compute_clip_similarity=True,
    output_dir=None,
    ngram_range=(3, 20),
    enable_wandb=True,
    log_frequency=10,
    model_type="open_clip",
    model_name="ViT-B-32-quickgelu",
    pretrained="laion400m_e32",
    device=0,
    max_batch_size=int(2e5),
    debug=False,
    wandb_log_frequency=1000,
    matching_threshold=0.3,
    perplexity_lm_name="laion2B-en",
    filter_by_lang=False,
):
    output_dir = os.path.abspath("output") if output_dir is None else output_dir
    log_frequency = 1 if debug else log_frequency
    wandb_log_frequency = 1 if debug else wandb_log_frequency

    print(locals())

    if convert:
        if filename is None:
            raise ValueError("Specify filename to convert")

        converted_filename = convert_to_image_url_text_parquet(filename, debug)

    if download_imgs:
        if not convert and converted_filename is None:
            raise ValueError(
                "Either set 'convert' to True or specify converted filename"
            )

        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)

        download(
            processes_count=36,
            thread_count=32,
            url_list=converted_filename,
            image_size=256,
            output_folder=output_dir,
            output_format="webdataset",
            input_format="parquet",
            url_col="URL",
            caption_col="TEXT",
            enable_wandb=enable_wandb,
            number_sample_per_shard=1000,
            distributor="multiprocessing",
        )

    config_to_log = locals()

    if compute_clip_similarity:
        filenames = [
            os.path.join(output_dir, filename)
            for filename in os.listdir(output_dir)
            if "tar" in filename
        ]

        # Create model
        model = get_model(model_type, model_name, pretrained, device, max_batch_size)

        perplexity_lm = load_perplexity_language_model(perplexity_lm_name)

        dataset = wds.WebDataset(filenames).decode("pil")

        # Wandb stuff
        if enable_wandb:
            wandb.init(
                project="img_text_pairs",
                entity="sid1793",
                mode="online",
                config=config_to_log,
            )
        predictions_table_data = []
        predictions_table_cols = ["Image", "Predicted text", "Score"]
        stats_table_cols = ["Description", "Fraction", "Counts"]

        # Dict for maintaining counts
        raw_counts = Counter()

        # Loop through the images dir
        for idx, sample in enumerate(iter(dataset)):
            raw_counts["total_imgs"] += 1

            # Read in image and text
            text = sample["txt"]
            image = sample["jpg"]

            # Split text into before and after
            before_text, after_text = get_before_after_text(text)

            before_lang = cld3.get_language(before_text)
            after_lang = cld3.get_language(after_text)

            if before_lang is not None:
                lang = before_lang.language
                raw_counts[f"before_{lang}"] += 1

            if after_lang is not None:
                lang = after_lang.language
                raw_counts[f"after_{lang}"] += 1

            # Compute and filter ngrams
            candidates = []

            if before_lang is not None:
                candidates.extend(
                    get_filtered_ngrams(
                        before_text,
                        ngram_range,
                        before_lang.language,
                        filter_by_lang,
                        perplexity_lm,
                    )
                )

            if after_lang is not None:
                candidates.extend(
                    get_filtered_ngrams(
                        after_text,
                        ngram_range,
                        after_lang.language,
                        filter_by_lang,
                        perplexity_lm,
                    )
                )

            if len(candidates) > 0:
                raw_counts["num_candidates_scored"] += 1

                torch.cuda.synchronize()
                start_time = time.time()
                # Compute embeddings
                with torch.no_grad(), torch.cuda.amp.autocast():
                    image_features = model.encode_image(image)
                    text_features = model.encode_text(candidates)

                    image_features /= image_features.norm(dim=-1, keepdim=True)
                    text_features /= text_features.norm(dim=-1, keepdim=True)

                    dot_prod = image_features @ text_features.T

                    maximum, argmax = dot_prod.max(dim=-1)

                torch.cuda.synchronize()
                end_time = time.time()
                raw_counts["inference_time"] += end_time - start_time

                prediction = candidates[argmax.cpu().item()]
                score = maximum.cpu().item()

                if score >= matching_threshold:
                    raw_counts["matches"] += 1

                    if enable_wandb:
                        num_pred_rows = len(predictions_table_data)

                        # wandb recommends logging a table of only 200000 rows
                        if num_pred_rows >= 200000:
                            continue

                        predictions_table_data.append(
                            [wandb.Image(image), prediction, score]
                        )

                num_rows_to_log = len(predictions_table_data)
                if (
                    (num_rows_to_log > 0)
                    and ((num_rows_to_log % wandb_log_frequency) == 0)
                    and enable_wandb
                ):
                    predictions_table = wandb.Table(
                        columns=predictions_table_cols, data=predictions_table_data
                    )
                    wandb.log({"predictions_table": predictions_table})

                    stats_table = get_stats_table(raw_counts, stats_table_cols)
                    wandb.log({"stats_table": stats_table})

            if (idx % log_frequency) == 0:
                # print (raw_counts)
                logging.info(
                    f"Num images: {raw_counts['total_imgs']}, Num scored: {raw_counts['num_candidates_scored']}, Num matches: {raw_counts['matches']}"
                )

        num_pred_rows = len(predictions_table_data)
        if num_pred_rows <= 200000:
            if enable_wandb:
                predictions_table = wandb.Table(
                    columns=predictions_table_cols, data=predictions_table_data
                )
                wandb.log({"predictions_table": predictions_table})

        if enable_wandb:
            stats_table = get_stats_table(raw_counts, stats_table_cols)
            wandb.log({"stats_table": stats_table})


if __name__ == "__main__":
    fire.Fire(run_pipeline)
