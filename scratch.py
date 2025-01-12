import pandas as pd

url = 'https://gitlab.com/drsantam/chavi-lookup-data/-/raw/main/lookup_datasets/uniprot.csv?inline=false'

df = pd.read_csv(url)
df.info()

print(df.nunique())