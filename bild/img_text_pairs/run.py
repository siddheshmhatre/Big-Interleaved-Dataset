import os
import time
import wandb
import torch
import shutil
import cld3
import fire
import webdataset as wds
from img2dataset import download
import open_clip
from utils import convert_to_image_url_text_parquet, get_filtered_ngrams, get_before_after_text

def run_pipeline(filename, 
                 convert=True, 
                 download_imgs=True, 
                 compute_clip_similarity=True, 
                 ngram_range=(3, 20), 
                 enable_wandb=True, 
                 log_frequency=1000,
                 matching_threshold=0.3):

    output_dir = os.path.abspath("output")

    if convert:
        converted_filename = convert_to_image_url_text_parquet(filename)
    else:
        converted_filename = filename

    if download_imgs:
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

    if compute_clip_similarity:
        # TODO - take care of this
        filenames = [os.path.join(output_dir, filename) for filename in os.listdir(output_dir) if "tar" in filename]

        # Create model
        model, _, preprocess = open_clip.create_model_and_transforms('ViT-B-32-quickgelu', pretrained='laion400m_e32')
        model = model.to('cuda')
        clip_tokenizer = open_clip.get_tokenizer('ViT-B-32-quickgelu')

        dataset = wds.WebDataset(filenames).decode("pil")

        # Wandb stuff
        if enable_wandb:
            wandb.init(project="img_text_pairs", entity="sid1793", mode="online")
        predictions_table_data = []
        predictions_table_cols = ["Image", "Predicted text", "Score"]
        stats_table_cols = ["Description", "Fraction", "Counts"]

        # Dict for maintaining counts
        raw_counts = {'total' : 0,
                      'num_english' : 0,
                      'inference_time' : 0,
                      'matches' : 0}

        # Loop through the images dir
        for idx, sample in enumerate(iter(dataset)):
            raw_counts['total'] += 1

            # Read in image and text 
            text = sample['txt']
            image = sample['jpg']

            # Split text into before and after
            before_text, after_text = get_before_after_text(text)

            before_lang = cld3.get_language(before_text)
            after_lang = cld3.get_language(after_text)

            # Check if English
            if before_lang is None or before_lang.language != "en":
                before_text = ""

            if after_lang is None or after_lang.language != "en":
                after_text = ""

            # Compute and filter ngrams
            candidates = get_filtered_ngrams(before_text, after_text, ngram_range)

            if len(candidates) > 0:
                raw_counts['num_english'] += 1

                torch.cuda.synchronize()
                start_time = time.time()
                # Compute embeddings
                with torch.no_grad(), torch.cuda.amp.autocast():

                    inp_image = preprocess(image).unsqueeze(0).to('cuda')
                    tokenized_text = clip_tokenizer(candidates).to('cuda')

                    if tokenized_text.shape[0] > 1024:
                        num_candidates = tokenized_text.shape[0]
                        text_features = torch.zeros([num_candidates, 512]).to('cuda')
                        for i in range(0, num_candidates, 1024):
                            tokenized_text_sub = tokenized_text[i:i+1024]
                            text_features[i:i+1024] = model.encode_text(tokenized_text_sub)

                    else:
                        text_features = model.encode_text(tokenized_text)

                    image_features = model.encode_image(inp_image)

                    image_features /= image_features.norm(dim=-1, keepdim=True)
                    text_features /= text_features.norm(dim=-1, keepdim=True)

                    dot_prod = image_features @ text_features.T
                
                    maximum, argmax = dot_prod.max(dim=-1)

                torch.cuda.synchronize()
                end_time = time.time()
                raw_counts['inference_time'] += (end_time - start_time)

                prediction = candidates[argmax.cpu().item()]
                score = maximum.cpu().item()

                if score >= matching_threshold:
                    raw_counts['matches'] += 1

                if enable_wandb:
                    predictions_table_data.append([wandb.Image(image), prediction, score])

                    num_pred_rows = len(predictions_table_data)

                    # wandb recommends logging a table of only 200000 rows
                    if num_pred_rows >= 200000:
                        continue

                if (len(predictions_table_data) % log_frequency) == 0:

                    if enable_wandb:
                        predictions_table = wandb.Table(columns=predictions_table_cols, data=predictions_table_data)
                        wandb.log({"predictions_table" : predictions_table})

                    print (raw_counts)

            if (idx % log_frequency) == 0:
                print (raw_counts)

        num_pred_rows = len(predictions_table_data)
        if num_pred_rows <= 200000:

            if enable_wandb:
                predictions_table = wandb.Table(columns=predictions_table_cols, data=predictions_table_data)
                wandb.log({"predictions_table" : predictions_table})

        # Logging for stats 
        stats_table_data = []

        for key, val in raw_counts.items():
            stats_table_data.append([key, val / raw_counts['total'], val])

        if enable_wandb:
            stats_table = wandb.Table(columns=stats_table_cols, data=stats_table_data)
            wandb.log({"stats_table" : stats_table})

if __name__ == "__main__":
    fire.Fire(run_pipeline)