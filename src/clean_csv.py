#!/usr/bin/env python
"""Smart CSV cleaner and scorer for Upwork job data using modular pipelines.

This version improves on numeric conversions by using pd.to_numeric with error coercion
and adds more robust handling for empty strings in fields like 'hourly_rate'. The modular
pipeline remains, making it easy to follow and maintain.
"""

import pandas as pd
import argparse
import gspread
import json
import os  # Import the 'os' module
from googleapiclient.discovery import build
from google.oauth2 import service_account

# ---------------------------
# Constants & Configurations
# ---------------------------
COLUMN_MAP = {
    'sr-only 6': 'rating',
    'd-inline-block': 'total_spent_by_client',
    'd-inline-flex': 'country',
    'text-light 8': 'payment_verified',
    'air3-link href': 'job_url_main',
    'air3-link': 'job_title',
    'air3-line-clamp': 'job_description',
    'text-caption 2': 'time_posted',
    'text-light 2': 'hourly_rate',
    'text-light 4': 'skill_level',
    'text-light 6': 'estimated_time',
    'text-light 7': 'estimated_budget'
}

TAG_COLUMNS = [f'air3-token' if i == 1 else f'air3-token {i}' for i in range(1, 9)]

SCORE_WEIGHTS = {
    'total_spent': 0.4,
    'proposed_rate': 0.25,
    'rating': 0.15,
    'skill_level': 0.1,
    'time_commitment': 0.1
}

# ---------------------------
# Core Functionality
# ---------------------------
def load_data(input_csv: str) -> pd.DataFrame:
    """Load and validate CSV data with robust error handling."""
    try:
        return pd.read_csv(input_csv, sep='\t')
    except FileNotFoundError:
        exit(f"Error: Input file not found at {input_csv}")
    except pd.errors.EmptyDataError:
        exit(f"Error: Empty input file {input_csv}")
    except pd.errors.ParserError:
        exit(f"Error: Malformed data in {input_csv}")

def transform_data(df: pd.DataFrame) -> pd.DataFrame:
    """Perform all data transformations in a single pipeline."""
    return (df
            .pipe(select_and_rename_columns)
            .pipe(process_tags)
            .pipe(convert_numerics)
            .pipe(filter_valid_rows)
            .pipe(calculate_scores)
            .pipe(clean_strings)
    )

def select_and_rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Select and rename required columns."""
    return df[list(COLUMN_MAP) + TAG_COLUMNS].rename(columns=COLUMN_MAP)

def process_tags(df: pd.DataFrame) -> pd.DataFrame:
    """Consolidate tag columns into a single list."""
    return df.assign(
        tags=df[TAG_COLUMNS].apply(lambda x: x.dropna().tolist(), axis=1)
    ).drop(columns=TAG_COLUMNS)

def convert_numerics(df: pd.DataFrame) -> pd.DataFrame:
    """Convert all numeric columns using vectorized operations."""
    # Convert rating (extract numeric part), hourly_rate, and estimated_budget robustly.
    df = df.copy()
    df['rating'] = pd.to_numeric(
        df['rating'].str.extract(r'(\d+\.?\d*)')[0],
        errors='coerce'
    ).fillna(0)
    
    df['total_spent_by_client'] = df['total_spent_by_client'].apply(parse_currency)
    
    # For estimated_budget, remove commas and convert
    df['estimated_budget'] = pd.to_numeric(
        df['estimated_budget']
          .str.extract(r'\$([\d,]+)')[0]
          .str.replace(',', '', regex=False),
        errors='coerce'
    ).fillna(0)
    
    # For hourly_rate, remove all non-digit and non-decimal characters.
    # Also, replace empty strings (if any) with '0' before converting.
    df['hourly_rate'] = pd.to_numeric(
        df['hourly_rate']
          .str.replace(r'[^\d.]', '', regex=True)
          .replace('', '0'),
        errors='coerce'
    ).fillna(0)
    
    return df

def parse_currency(value: str) -> float:
    """Parse currency values with K/M suffixes.
    
    Converts strings like '$5K' or '$3.2M' into their float representations.
    """
    if pd.isna(value) or value == '$0':
        return 0.0
    value = value.replace('$', '').replace('+', '')
    multiplier = 1
    if 'K' in value:
        multiplier = 1000
        value = value.replace('K', '')
    elif 'M' in value:
        multiplier = 1_000_000
        value = value.replace('M', '')
    try:
        return float(value) * multiplier
    except ValueError:
        return 0.0

def filter_valid_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Filter rows based on business rules."""
    return df.query("payment_verified == 'Payment verified' and total_spent_by_client > 0")

def calculate_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate golden scores using vectorized operations."""
    df = df.drop(columns=['earning_potential', 'job_score'], errors='ignore')
    
    # Pre-calculate maxima once for normalization
    max_total = df['total_spent_by_client'].max()
    max_rate = df['hourly_rate'].max() * 120  # 30 hrs/week * 4 weeks
    
    # Calculate components for scoring.
    # Here, we assume that estimated_time contains '30+' if the project is high commitment.
    time_multiplier = (
        df['estimated_time'].str.contains('30+', na=False)
        .map({True: 30, False: 15})
        .astype('int64')  # Explicit type conversion
        * 4
    )
    skill_scores = df['skill_level'].map({'Expert': 3, 'Intermediate': 2}).fillna(1)
    time_scores = df['estimated_time'].str.contains('30+').astype(int) + 1
    
    # Form normalized scores for each component.
    norms = pd.DataFrame({
        'total_spent': df['total_spent_by_client'] / max_total,
        'proposed_rate': (df['hourly_rate'] * time_multiplier) / max_rate,
        'rating': df['rating'] / 5,
        'skill_level': skill_scores / 3,
        'time_commitment': time_scores / 2
    })
    
    # Compute the final score using a weighted sum on normalized components,
    # round to 2 decimals, then scale to a 0-100 score.
    df['golden_score'] = (norms * pd.Series(SCORE_WEIGHTS)).sum(axis=1).round(2) * 100
    return df.sort_values('golden_score', ascending=False)

def clean_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Escape double quotes in string columns as per RFC 4180."""
    str_cols = df.select_dtypes(include='object').columns
    df[str_cols] = df[str_cols].apply(lambda x: x.str.replace('"', '""', regex=False))
    return df

def save_data(df: pd.DataFrame, output_csv: str) -> None:
    """Save the transformed data to CSV with proper formatting."""
    df.to_csv(output_csv, index=False, quoting=1, quotechar='"', encoding='utf-8')

# --- Google Sheets Integration ---
def connect_to_google_sheets():
    credentials = service_account.Credentials.from_service_account_file(
        'google_creds.json',
        # Add drive scope for file creation/sharing
        scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
    )
    return gspread.authorize(credentials)

def save_to_google_sheets(df: pd.DataFrame, spreadsheet_name: str, worksheet_name: str = 'Sheet1', user_email: str = None):
    """Saves the DataFrame to a Google Sheet using official Google API methods."""
    try:
        # Update scopes here too
        credentials = service_account.Credentials.from_service_account_file(
            'google_creds.json',
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
        )
        
        # Initialize client and drive service with same credentials
        gc = gspread.authorize(credentials)
        drive_service = build('drive', 'v3', credentials=credentials)

        # Spreadsheet handling
        try:
            sh = gc.open(spreadsheet_name)
        except gspread.SpreadsheetNotFound:
            sh = gc.create(spreadsheet_name)
            # Immediately share with service account email (critical step)
            sh.share(
                credentials.service_account_email,  # Use credentials property directly
                perm_type='user', 
                role='writer'
            )

        # Worksheet handling
        try:
            worksheet = sh.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            worksheet = sh.add_worksheet(
                title=worksheet_name, 
                rows=max(df.shape[0]+1, 100),
                cols=max(df.shape[1]+1, 20)
            )

        # Data upload
        worksheet.clear()
        worksheet.update(
            [df.columns.values.tolist()] + df.fillna('').values.tolist(),
            value_input_option='USER_ENTERED'
        )

        # User sharing
        if user_email:
            drive_service.permissions().create(
                fileId=sh.id,
                body={'type': 'user', 'role': 'writer', 'emailAddress': user_email},
                fields='id',
                sendNotificationEmail=True
            ).execute()

        print(f"Success: {sh.url}")

    except gspread.exceptions.APIError as e:  # Corrected exception
        print(f"Google API Error: {e.response.json()['error']['message']}")
    except Exception as e:
        print(f"General Error: {str(e)}")


# ---------------------------
# Main Execution
# ---------------------------
def main():
    parser = argparse.ArgumentParser(description='Process Upwork job data')
    parser.add_argument('input_file', help='Input CSV file path')
    parser.add_argument('output_file', help='Output CSV file path')
    # Add an argument for the Google Sheet name
    parser.add_argument('--sheet_name', help='Google Sheet name', default='Upwork Job Data')
     # Add an argument for the Google Sheet worksheet name
    parser.add_argument('--worksheet_name', help='Google Sheet worksheet name', default='Sheet1')
    # Add arg for user email
    parser.add_argument('--user_email', help='Email to share the sheet with', default=None)

    args = parser.parse_args()
    
    df = load_data(args.input_file)
    transformed_df = transform_data(df)
    save_data(transformed_df, args.output_file)
    # Save to Google Sheets
    save_to_google_sheets(transformed_df, args.sheet_name, args.worksheet_name, args.user_email)
    print(f"Successfully processed {len(df)} jobs to {args.output_file}")

if __name__ == '__main__':
    main()