import pandas as pd
import sqlite3

csv_file = 'Employers_data.csv'
df = pd.read_csv(csv_file)

df_employees = df[['Employee_ID', 'Name', 'Age', 'Gender', 'Department', 'Job_Title', 'Location']]

df_details = df[['Employee_ID', 'Experience_Years', 'Education_Level', 'Salary']]

conn = sqlite3.connect('conversation.db')

df_employees.to_sql('employees', conn, if_exists='replace', index=False)

df_details.to_sql('details', conn, if_exists='replace', index=False)

conn.close()