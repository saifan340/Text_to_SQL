import pandas as pd
import sqlite3

# Load CSV file
csv_file = 'employers_data.csv'
df = pd.read_csv(csv_file)

# Show first rows (optional)
print("Preview of CSV:")
print(df.head())

# Connect to SQLite (creates db file if not exists)
conn = sqlite3.connect('employer.db')

# Save DataFrame to table 'employees'
df.to_sql('employees', conn, if_exists='replace', index=False)

print("✅ Data inserted into 'employees' table in employer.db")

# Close connection
conn.close()
