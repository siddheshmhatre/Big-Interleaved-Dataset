#!/bin/bash
#SBATCH --partition=g80n60
#SBATCH --nodes 1
#SBATCH --gpus 8
#SBATCH --comment laion
#SBATCH --output=/fsx/home-siddhesh1793/logs/%x_%j.out
#SBATCH --exclusive
#SBATCH --job-name=bild_img_txt_pairs_clip_filtering

# HOSTNAMES MASTER_ADDR MASTER_PORT COUNT_NODE are coming from the main script

echo myuser=`whoami`
echo LD_LIBRARY_PATH=$LD_LIBRARY_PATH
echo PATH=$PATH
echo HOSTNAMES=$HOSTNAMES
echo hostname=`hostname`

# ARGS
CONVERT="False"
echo CONVERT=$CONVERT

DOWNLOAD_IMGS="False"
echo DOWNLOAD_IMGS=$DOWNLOAD_IMGS

MODEL_TYPE="xlm_roberta_large_vit_l14"
echo MODEL_TYPE=$MODEL_TYPE

# If MODEL_TYPE is xlm_roberta_large_vit_l14, then MODEL_NAME and PRETRAINEd wont be used
MODEL_NAME='xlm-roberta-large-ViT-H-14'
echo MODEL_NAME=$MODEL_NAME

PRETRAINED='frozen_laion5b_s13b_b90k'
echo PRETRAINED=$PRETRAINED

MATCHING_THRESHOLD=0.23
echo MATCHING_THRESHOLD=$MATCHING_THRESHOLD

ENABLE_WANDB="True"
echo ENABLE_WANDB=$ENABLE_WANDB

MAX_BATCH_SIZE=256
echo MAX_BATCH_SIZE=$MAX_BATCH_SIZE

FILTER_BY_LANG="False"
echo FILTER_BY_LANG=$FILTER_BY_LANG

LOG_FREQUENCY=1000
echo LOG_FREQUENCY=$LOG_FREQUENCY

DEVICE='cuda'
echo DEVICE=$DEVICE
# ARGS

#source /admin/home-siddhesh1793/.env/bin/activate
echo python3 version = `python3 --version`
python -c "import torch; print (torch.__version__)"

python run.py --convert $CONVERT \
				--download_imgs $DOWNLOAD_IMGS \
				--model_type $MODEL_TYPE \
				--model_name $MODEL_NAME \
				--pretrained $PRETRAINED \
				--matching_threshold $MATCHING_THRESHOLD \
				--enable_wandb $ENABLE_WANDB \
				--max_batch_size $MAX_BATCH_SIZE \
				--filter_by_lang $FILTER_BY_LANG \
				--log_frequency $LOG_FREQUENCY \
				--device $DEVICE