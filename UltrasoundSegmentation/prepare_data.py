"""
Read original data, apply transforms and save processed data to disk. Keep original data types and values.
Segmentations can have an arbitrary number of channels. All channels will be preserved.
Ultrasound images are assumed to have only one channel. Output ultrasound arrays will have N+1 channels,
where N is the number of preceding ultrasound images to use as input for the segmentation.
For data provenance, write processing log to a file and copy the configuration file in the output folder.
"""

import argparse
import cv2
import logging
import os
import numpy as np
import sys
import yaml

from tqdm import tqdm

# Parse command line arguments

parser = argparse.ArgumentParser()
parser.add_argument("--input_dir", type=str, default="data")
parser.add_argument("--output_dir", type=str, default="data_prepared")
parser.add_argument("--config_file", type=str)
parser.add_argument("--log_level", type=str, default="INFO")
parser.add_argument("--log_file", type=str)
args = parser.parse_args()

print(f"Input directory: {args.input_dir}")
print(f"Output directory: {args.output_dir}")
print(f"Config file: {args.config_file}")
print(f"Log level: {args.log_level}")
print(f"Log file: {args.log_file}")

# Make sure output folder exists and save a copy of the configuration file

if not os.path.exists(args.output_dir):
    os.makedirs(args.output_dir)

# Set up logging into file or console

if args.log_file is not None:
    log_file = os.path.join(args.output_dir, args.log_file)
    logging.basicConfig(filename=log_file, filemode="w", level=args.log_level)
else:
    logging.basicConfig(level=args.log_level)  # Log to console

# Find all data files in input directory

input_dir = args.input_dir
data_files = []
for seg_filename in os.listdir(input_dir):
    if seg_filename.endswith(".npy") and "_segmentation" in seg_filename:
        data_files.append(os.path.join(input_dir, seg_filename))

print(f"Found {len(data_files)} data files.")

# Read config file

if args.config_file is None:
    args.config_file = os.path.join(os.path.abspath(os.path.dirname(__file__)), "prepare_data_config.yaml")

with open(args.config_file, "r") as f:
    config = yaml.safe_load(f)

with open(os.path.join(args.output_dir, "prepare_data_config.yaml"), "w") as f:
    yaml.dump(config, f)


# Read input files, process and filter data, and save new data to disk

for seg_filename in tqdm(data_files):
    data = np.load(seg_filename)
    logging.info(f"Loaded {seg_filename} with shape {data.shape} and value range {np.min(data)} - {np.max(data)}")

    # Filter data. Keep only segmented ultrasound images with indices stored in _indices.npy file.

    indices_filename = seg_filename.replace("_segmentation", "_indices")
    if os.path.exists(indices_filename):
        indices = np.load(indices_filename)
        logging.info(f"Loaded {indices_filename} with shape {indices.shape}")
        data = data[indices, :, :, :]
        logging.info(f"Filtered data to shape {data.shape}")
    else:
        logging.info("No indices file found. Keeping all data.")

    # Resize segmentation images channel by channel.

    resized_data = np.zeros((data.shape[0], config["image_size"], config["image_size"], data.shape[3]), dtype=data.dtype)
    for i in range(data.shape[0]):
        for j in range(data.shape[3]):
            resized_data[i, :, :, j] = cv2.resize(data[i, :, :, j], (config["image_size"], config["image_size"]))

    # Save resized images to disk

    output_filename = os.path.join(args.output_dir, os.path.basename(seg_filename))
    np.save(output_filename, resized_data)
    logging.info(f"Saved {output_filename} with shape {resized_data.shape} and value range {np.min(resized_data)} - {np.max(resized_data)}")

    # Find matching ultrasound file and read ultrasound data

    ultrasound_filename = seg_filename.replace("_segmentation", "_ultrasound")
    if not os.path.exists(ultrasound_filename):
        logging.error(f"Could not find matching ultrasound file for {seg_filename}")
        sys.exit(1)
    
    ultrasound_data = np.load(ultrasound_filename)
    logging.info(f"Loaded {ultrasound_filename} with shape {ultrasound_data.shape} and value range {np.min(ultrasound_data)} - {np.max(ultrasound_data)}")

    # Keep only ultrasound images that have a corresponding segmentation image, with preceding ultrasound frames as requested in separate channels
    # If there are not enough preceding ultrasound frames, pad extra channels with zeros.

    if config["num_preceding_ultrasound_frames"] < 0:
        logging.error("num_preceding_ultrasound_frames must be >= 0")
        sys.exit(1)

    resized_data = np.zeros((data.shape[0], config["image_size"], config["image_size"], config["num_preceding_ultrasound_frames"] + 1), dtype=ultrasound_data.dtype)
    
    for i in range(data.shape[0]):
        for j in range(config["num_preceding_ultrasound_frames"] + 1):
            if i - j >= 0:
                resized_data[i, :, :, j] = cv2.resize(ultrasound_data[indices[i - j], :, :, 0], (config["image_size"], config["image_size"]))
    
    # Save resized images to disk

    output_filename = os.path.join(args.output_dir, os.path.basename(ultrasound_filename))
    np.save(output_filename, resized_data)
    logging.info(f"Saved {output_filename} with shape {resized_data.shape} and value range {np.min(resized_data)} - {np.max(resized_data)}")

    # Load transform file and keep only the transforms that correspond to the segmented ultrasound image

    transform_filename = seg_filename.replace("_segmentation", "_transform")
    if os.path.exists(transform_filename):
        transform_data = np.load(transform_filename)
        logging.info(f"Loaded {transform_filename} with shape {transform_data.shape}")
        transform_data = transform_data[indices, :, :]
        output_filename = os.path.join(args.output_dir, os.path.basename(transform_filename))
        np.save(output_filename, transform_data)
        logging.info(f"Saved {output_filename} with shape {transform_data.shape}")
    else:
        logging.info(f"No transform file found for {seg_filename}")

    # Copy indices file to output folder

    output_filename = os.path.join(args.output_dir, os.path.basename(indices_filename))
    with open(indices_filename, "rb") as f:
        with open(output_filename, "wb") as f_out:
            f_out.write(f.read())
    logging.info(f"Copied {indices_filename} to {output_filename}")