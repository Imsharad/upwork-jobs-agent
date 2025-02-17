# this script parses the "scraped" upwork job data and cleans it
# it also calculates a job score for each job

import os
import pandas as pd
import csv

# Construct the path relative to this script file
input_csv = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw', 'list8.csv')
df = pd.read_csv(input_csv, sep='\t')

# Define column mapping for non-tag columns
column_mapping = {
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

# Identify tag columns explicitly
tag_columns = [
    'air3-token',
    'air3-token 2',
    'air3-token 3',
    'air3-token 4',
    'air3-token 5',
    'air3-token 6',
    'air3-token 7',
    'air3-token 8'
]

# Create a list of columns to keep initially (non-tag columns)
columns_to_keep = list(column_mapping.keys()) + tag_columns

# Keep only the desired columns and tag columns
df = df[columns_to_keep]

# Rename the non-tag columns
df = df.rename(columns=column_mapping)

# Create 'tags' column by combining all tag columns into a list
df['tags'] = df[tag_columns].apply(lambda row: [tag for tag in row.dropna().tolist() if pd.notna(tag)], axis=1)

# Remove original tag columns
df = df.drop(columns=tag_columns)

# Extract numeric rating from the rating column
df['rating'] = df['rating'].str.extract(r'(\d+\.?\d*)').astype(float)

# Convert total_spent_by_client to numeric values
def convert_spending(value):
    if pd.isna(value) or value == '$0':
        return 0
    # Remove all non-numeric characters except '.' and '+'
    cleaned_value = value.replace('$', '').replace('K+', '').replace('M+', '').replace('+', '')
    try:
        numeric_value = float(cleaned_value)
    except ValueError:
        return 0
    multiplier = 1
    if 'K+' in value:
        multiplier = 1000
    elif 'M+' in value:
        multiplier = 1000000
    return numeric_value * multiplier

df['total_spent_by_client'] = df['total_spent_by_client'].apply(convert_spending)

# Extract estimated budget
def extract_budget(value):
    if 'Est. Budget:' not in value:
        return 0
    try:
        return float(value.replace('Est. Budget:', '').replace('$', '').replace(',', ''))
    except:
        return 0

df['estimated_budget'] = df['estimated_budget'].apply(extract_budget)

# Convert hourly_rate to numeric values
def convert_hourly_rate(value):
    if pd.isna(value) or value == '$0':
        return 0
    # Remove all non-numeric characters except '.'
    cleaned_value = value.replace('$', '').replace('-', '').replace(',', '')
    try:
        return float(cleaned_value)
    except ValueError:
        return 0

df['hourly_rate'] = df['hourly_rate'].apply(convert_hourly_rate)

# ----------------------------------------------------------------
# New cleaning conditions:
# Drop rows where payment_verified is not "Payment verified"
# or where total_spent_by_client is zero.
# ----------------------------------------------------------------
df = df[(df['payment_verified'] == 'Payment verified') & (df['total_spent_by_client'] != 0)]
# ----------------------------------------------------------------

# Create golden score
def calculate_golden_score(row):
    # The following early check is now redundant because we have filtered out unqualified rows.
    # However, we leave the rating check in place.
    if row['rating'] == 0:
        return 0

    # Weighted scoring components
    weights = {
        'total_spent': 0.4,        # Past client spending indicates trust and reliability
        'proposed_rate': 0.25,     # Current earning potential
        'rating': 0.15,            # Client credibility
        'skill_level': 0.1,        # Job complexity (higher for expert)
        'time_commitment': 0.1     # Project duration/stability
    }

    # Calculate individual components
    total_spent = row['total_spent_by_client']
    proposed_rate = row['hourly_rate'] * (30 if '30+ hrs/week' in row['estimated_time'] else 15) * 4
    rating = row['rating']

    # Skill level scoring
    skill_level = 3 if row['skill_level'] == 'Expert' else 2 if row['skill_level'] == 'Intermediate' else 1

    # Time commitment scoring
    time_commitment = 2 if '30+ hrs/week' in row['estimated_time'] else 1

    # Normalize values
    max_total_spent = df['total_spent_by_client'].max()
    max_proposed_rate = df['hourly_rate'].max() * 30 * 4

    normalized_total_spent = (total_spent / max_total_spent) if max_total_spent > 0 else 0
    normalized_proposed_rate = (proposed_rate / max_proposed_rate) if max_proposed_rate > 0 else 0

    # Calculate final score
    score = (
        (normalized_total_spent * weights['total_spent']) +
        (normalized_proposed_rate * weights['proposed_rate']) +
        (rating / 5 * weights['rating']) +  # Normalize rating to 0-1
        (skill_level / 3 * weights['skill_level']) +  # Normalize skill level to 0-1
        (time_commitment / 2 * weights['time_commitment'])  # Normalize time commitment to 0-1
    )

    # Scale to 0-100 for easier interpretation
    return round(score * 100, 2)

# Remove old scoring columns and add golden_score
df = df.drop(columns=['earning_potential', 'job_score'], errors='ignore')
df['golden_score'] = df.apply(calculate_golden_score, axis=1)

# Sort by golden_score in descending order
df = df.sort_values(by='golden_score', ascending=False)

# Add this preprocessing step before saving
def clean_field(field):
    if isinstance(field, str):
        # Escape double quotes by doubling them (RFC 4180 standard)
        return field.replace('"', '""')
    return field

# Apply cleaning to all fields (updated to use map instead of applymap)
df = df.map(clean_field)

# Save with proper CSV formatting
output_csv = os.path.join(os.path.dirname(__file__), '..', 'data', 'cleaned', 'cleaned_list8.csv')
df.to_csv(
    output_csv,
    index=False,
    sep=',',
    quoting=csv.QUOTE_NONNUMERIC,
    quotechar='"',
    lineterminator='\n',
    encoding='utf-8'
)
print("CSV file has been cleaned and saved as cleaned_list8.csv")