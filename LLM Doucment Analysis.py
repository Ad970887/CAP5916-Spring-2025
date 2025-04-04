!pip install requests beautifulsoup4 spacy pandas openai
!python -m spacy download en_core_web_sm
!pip install openai==0.28.0
import requests
import csv
import time
import spacy
from bs4 import BeautifulSoup
import pandas as pd
import openai
import os
from datetime import datetime

# Load spaCy model (for potential future use, e.g. further NER)
nlp = spacy.load('en_core_web_sm')

# Set your OpenAI API key here (replace with your own key)
api_key = "API_KEY"
os.environ["OPENAI_API_KEY"] = api_key
openai.api_key = os.environ["OPENAI_API_KEY"]

# Global variables
HEADERS = {
    "User-Agent": "Name ("email") for academic 8-K analysis"
}
CSV_FILE = "SP500_8K_Filings.csv"

# Global counter for valid product entries
PRODUCT_COUNT = 0
MAX_PRODUCTS = 100

print("Module 1: Setup complete!")

def get_all_tickers_from_sec():
    """
    Fetches the SEC company tickers JSON and returns a dictionary mapping ticker symbols
    to a tuple of (zero-padded CIK, Company Name).
    """
    url = "https://www.sec.gov/files/company_tickers.json"
    response = requests.get(url, headers=HEADERS, timeout=10)
    ticker_map = {}
    if response.status_code == 200:
        data = response.json()
        for _, entry in data.items():
            ticker = entry.get("ticker", "").upper()
            cik = entry.get("cik_str", "")
            title = entry.get("title", "")
            if ticker and cik and title:
                ticker_map[ticker] = (str(cik).zfill(10), title)
    else:
        print("Failed to fetch ticker data.")
    return ticker_map

def fetch_latest_filings(cik, count=10):
    """Fetches the latest SEC Form 8-K filings for a given company CIK."""
    try:
        search_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&count={count}&output=atom"
        response = requests.get(search_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.content, "xml")
        entries = soup.find_all("entry")
        filing_urls = [(entry.find("link")["href"], entry.find("updated").text) for entry in entries]
        return filing_urls
    except Exception as e:
        print(f"Error fetching filings for CIK {cik}: {e}")
        return []

def extract_filing_text(filing_url):
    """
    Extracts the complete 8-K filing text by:
      1. Fetching the filing detail page,
      2. Locating the "Complete submission text file" link,
      3. Fetching and returning that document.
    """
    try:
        response = requests.get(filing_url, headers=HEADERS, timeout=10)
        if response.status_code == 404:
            print(f"Error 404: Document not found for URL: {filing_url}")
            return "ErrorDocument: 404 Not Found"
        soup = BeautifulSoup(response.text, "html.parser")

        complete_link = None
        for row in soup.find_all("tr"):
            if "Complete submission text file" in row.get_text():
                a_tag = row.find("a")
                if a_tag and a_tag.get("href"):
                    complete_link = a_tag["href"]
                    break
        if not complete_link:
            print("Could not find the 'Complete submission text file' link.")
            return "ErrorDocument: No complete text link found"

        if not complete_link.startswith("http"):
            complete_link = "https://www.sec.gov" + complete_link

        doc_response = requests.get(complete_link, headers=HEADERS, timeout=10)
        if doc_response.status_code == 404:
            print(f"Error 404: Document not found for URL: {complete_link}")
            return "ErrorDocument: 404 Not Found"
        return doc_response.text
    except Exception as e:
        print(f"Error extracting text from {filing_url}: {e}")
        return "ErrorDocument: Unable to extract text"

# Suppose you already have a variable 'cik' from get_cik_from_ticker("AAPL")
filings = fetch_latest_filings('0000320193')  # This returns a list of (url, date) tuples

if len(filings) > 0:
    # Grab the first filing
    filing_url, filing_date = filings[0]
    # Now call extract_filing_text with this URL
    text = extract_filing_text(filing_url)
    print(text[:2000])  # Print the first 2000 characters
else:
    print("No filings found.")

def query_openai(text):
    """
    Uses the OpenAI API to extract product details.
    This function looks for keywords indicating product announcements and extracts a snippet.
    """
    keywords = ["launch", "introduce", "announce", "new product", "unveil"]
    snippet = None
    text_lower = text.lower()
    for kw in keywords:
        idx = text_lower.find(kw)
        if idx != -1:
            snippet = text[max(0, idx-500):idx+1500]
            break
    if not snippet:
        snippet = text[:2000]

    prompt = f"""You are an expert in analyzing SEC filings.
Examine the following SEC Form 8-K filing text snippet and extract details about any new product launch or announcement.
Return your answer exactly in this format:

Product Name: [Product Name]
Description: [Brief Description (Max 180 characters)]

If no new product is mentioned, return:
Product Name: None
Description: None

Filing Text:
{snippet}
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.5,
        )
        content = response.choices[0].message['content'].strip()
        print("DEBUG: Full API response:")
        print(content)
        product_name = "TBD"
        description = "TBD"
        for line in content.splitlines():
            if "Product Name:" in line:
                product_name = line.replace("Product Name:", "").strip()
            elif "Description:" in line:
                description = line.replace("Description:", "").strip()
        return product_name, description[:180]
    except Exception as e:
        print(f"Error querying OpenAI API: {e}")
        return "Error", "Error"

def process_company(ticker, company_name, cik):
    """
    Processes a single company: fetches filings, extracts text, queries OpenAI
    for product details, and appends results to CSV.
    Stops processing if 100 valid products have been saved.
    """
    global PRODUCT_COUNT
    try:
        print(f"Processing: {company_name} ({ticker}, CIK: {cik})")
        filings = fetch_latest_filings(cik)
        for filing_url, filing_date in filings:
            if PRODUCT_COUNT >= MAX_PRODUCTS:
                print("Reached maximum valid product count. Stopping further processing.")
                return
            text = extract_filing_text(filing_url)
            print(f"Filing URL: {filing_url}")
            print(f"Extracted Text Preview: {text[:500]}...")
            product_name, product_description = query_openai(text)
            if product_name.strip().lower() == "none":
                print("No product found in this filing, skipping...")
                continue
            try:
                formatted_date = pd.to_datetime(filing_date).strftime('%Y-%m-%d')
            except Exception as e:
                print(f"Error formatting date '{filing_date}': {e}")
                formatted_date = filing_date
            save_to_csv([company_name, ticker, formatted_date, product_name, product_description])
            PRODUCT_COUNT += 1
            print(f"Saved product #{PRODUCT_COUNT}: {product_name}")
            time.sleep(1)  # Respect SEC rate limits
            if PRODUCT_COUNT >= MAX_PRODUCTS:
                print("Reached maximum valid product count. Stopping further processing.")
                return
    except Exception as e:
        print(f"Error processing {ticker}: {e}")

def save_to_csv(data):
    """Appends extracted data to the CSV file."""
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(data)

def main():
    start_time = time.time()

    # Initialize CSV with headers
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Company Name", "Stock Name", "Filing Time", "New Product", "Product Description"])

    ticker_map = get_all_tickers_from_sec()

    # Process ALL tickers from SEC until 100 valid products are found
    for ticker, (cik, comp_name) in ticker_map.items():
        if PRODUCT_COUNT >= MAX_PRODUCTS:
            break
        process_company(ticker, comp_name, cik)

    elapsed = time.time() - start_time
    print(f"Processing complete! Total time: {elapsed/60:.2f} minutes")

    # Post-process CSV: sort by Filing Time and keep top 100 filings
    # Import pandas under its normal alias (make sure pd is not overwritten)
    df = pd.read_csv(CSV_FILE)
    df['Filing Time'] = pd.to_datetime(df['Filing Time'], errors='coerce', utc=True)
    df_sorted = df.sort_values(by="Filing Time", ascending=False)
    df_top_100 = df_sorted.head(100)
    df_top_100 = df_top_100[['Company Name', 'Stock Name', 'Filing Time', 'New Product', 'Product Description']]
    df_top_100.to_csv('Filtered_SP500_8K_Filings.csv', index=False, sep='|')

    print("Filtered data has been saved to 'Filtered_SP500_8K_Filings.csv'.")

    # Optionally display final DataFrame if using Colab
    from IPython.display import display
    display(df_top_100)

if __name__ == "__main__":
    main()
