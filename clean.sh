#!/bin/bash

# Create the output directory if it doesn't exist
mkdir -p data/cleaned

# Use $1 for input file, $2 for output file.  Provide defaults if not given.
input_file="${1:-data/raw/list8.csv}"
output_file="${2:-data/cleaned/cleaned_list8.csv}"

# Capture additional arguments for Google Sheets integration
extra_args=("${@:3}")

# Run the Python script with all arguments
python src/clean_csv.py "$input_file" "$output_file" "${extra_args[@]}"

# Run this command to update requirements.txt
pip freeze > requirements.txt 