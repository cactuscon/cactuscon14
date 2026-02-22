#!/usr/bin/env python3

#######################################################################
# pic_to_rgb565.py
# Converts images to raw RGB565 format for use in the CactusCon badge.
# This is a simple script that takes a folder of images and converts them
# to raw RGB565 format, which is a 16-bit color format used in many
# embedded systems and displays.
#
# Usage:
# python pic_to_rgb565.py <folder_path> [--swap-bytes]
# <folder_path> is the path to the folder containing the images to convert.
# --swap-bytes: Write little-endian (byte-swapped) output. Use this when
#               the target display has rgb565_byte_swap=True, to avoid
#               runtime byte swapping on the embedded device.
#
# The script will create new files with the same name as the original
# images, but with a .rgb565 extension.
#
# The converted files will be saved in the same folder as the original images.
# The script supports .png, .jpg, and .jpeg image formats.
#
# The script uses the Pillow library to handle image conversion.
# Make sure to install it with:
# pip install Pillow
#
# author: CactusCon Badge Team
# date: April 2025
# version: 0.2.0
#######################################################################

import os
from PIL import Image
import argparse
import struct
import math

def convert_image_to_rgb565(image, output_path, swap_bytes=False):
    """
    Convert image to RGB565 binary format.
    
    Args:
        image: PIL Image in RGB mode
        output_path: Path to write .rgb565 file
        swap_bytes: If True, write little-endian (for displays with rgb565_byte_swap=True)
                    If False, write big-endian (default, traditional format)
    """
    width, height = image.size
    # Use little-endian '<H' if swap_bytes, else big-endian '>H'
    pack_format = '<H' if swap_bytes else '>H'
    
    with open(output_path, 'wb') as f:
        for y in range(height):
            for x in range(width):
                r, g, b = image.getpixel((x, y))
                rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                f.write(struct.pack(pack_format, rgb565))

def flatten_sprite_grid(image):
    w, h = image.size
    grid_size = int(math.sqrt((w * h) // (min(w, h) ** 2)))

    if grid_size ** 2 * (w // grid_size) * (h // grid_size) != w * h:
        raise ValueError("Image doesn't appear to be a clean N×N grid")

    frame_w = w // grid_size
    frame_h = h // grid_size

    flat_img = Image.new("RGB", (frame_w * grid_size, frame_h))
    for i in range(grid_size ** 2):
        src_x = (i % grid_size) * frame_w
        src_y = (i // grid_size) * frame_h
        frame = image.crop((src_x, src_y, src_x + frame_w, src_y + frame_h))
        flat_img.paste(frame, (i * frame_w, 0))

    return flat_img

def batch_convert(folder_path, swap_bytes=False):
    supported_exts = ['.png', '.jpg', '.jpeg']
    endian_mode = "little-endian (swapped)" if swap_bytes else "big-endian"
    print(f"Converting images to RGB565 ({endian_mode})...")
    
    for filename in os.listdir(folder_path):
        name, ext = os.path.splitext(filename)
        if ext.lower() in supported_exts:
            input_path = os.path.join(folder_path, filename)
            output_path = os.path.join(folder_path, name + '.rgb565')

            if os.path.exists(output_path):
                print(f" - Skipping {filename}, already converted.")
                continue

            print(f"Processing {filename}...")

            img = Image.open(input_path).convert("RGB")
            w, h = img.size

            # If square and larger than typical sprite size, try to flatten it
            if w == h and w % 2 == 0:
                try:
                    print(" - Detected square grid, flattening...")
                    img = flatten_sprite_grid(img)
                except Exception as e:
                    print(f" - Skipped flatten: {e}")

            convert_image_to_rgb565(img, output_path, swap_bytes=swap_bytes)
            print(f" - Saved {os.path.basename(output_path)}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Convert images in a folder to raw RGB565 format.')
    parser.add_argument('folder', help='Path to folder containing .png/.jpg images')
    parser.add_argument('--swap-bytes', '-s', action='store_true',
                        help='Write little-endian (byte-swapped) output for displays with rgb565_byte_swap=True')
    args = parser.parse_args()

    batch_convert(args.folder, swap_bytes=args.swap_bytes)
