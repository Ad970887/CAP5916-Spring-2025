import requests
from bs4 import BeautifulSoup
import subprocess
import csv
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Constants
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
HEADERS = {"User-Agent": "ad970887@ucf.edu"}  # User-Agent to avoid blocking


# Email function (to notify completion)
def send_email(subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # Send the email using SMTP
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, RECEIVER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {str(e)}")

# Function to fetch top 100 companies
def get_top_100_companies(n=100):
    retries = 3
    for attempt in range(retries):
        response = requests.get(TICKERS_URL, headers=HEADERS)
        if response.status_code != 200:
            print(f"Attempt {attempt + 1}: Error - Received status code {response.status_code}")
            time.sleep(2)  # Wait before retrying
            continue

        try:
            tickers_data = response.json()
        except requests.exceptions.JSONDecodeError:
            print(f"Attempt {attempt + 1}: Error - Unable to decode the response as JSON.")
            print(f"Raw response: {response.text}")  # Debugging: print raw response
            time.sleep(2)
            continue

        companies = sorted(tickers_data.values(), key=lambda x: x["title"])[:n]
        return companies

    print("Failed to retrieve data after multiple attempts.")
    return []

# Function to get the latest 8-K filing for a company
def get_latest_8k_filing(cik):
    SEC_BASE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
    params = {
        "action": "getcompany",
        "CIK": cik,
        "type": "8-K",
        "count": 1,
        "output": "atom"
    }
    response = requests.get(SEC_BASE_URL, params=params, headers=HEADERS)
    if response.status_code != 200:
        print(f"Error: Received status code {response.status_code} for CIK {cik}")
        return None

    soup = BeautifulSoup(response.text, "xml")
    entry = soup.find("entry")

    if not entry:
        print(f"No 8-K filing found for CIK {cik}")
        return None

    filing_url = entry.find("link")["href"]
    filing_title = entry.find("title").text
    filing_time = entry.find("updated").text

    return {
        "title": filing_title,
        "url": filing_url,
        "filing_time": filing_time
    }

# Function to extract the text from the 8-K filing
def extract_filing_text(filing_url):
    response = requests.get(filing_url, headers=HEADERS)
    if response.status_code != 200:
        print(f"Error: Unable to fetch the filing content from {filing_url}")
        return "No text found."

    soup = BeautifulSoup(response.text, "html.parser")
    text = " ".join([p.text for p in soup.find_all("p")])
    return text if text else "No text found."

# Function to query Ollama API for product details
def query_ollama(text):
    prompt = f"""Extract details about any new product mentioned in this SEC Form 8-K filing.
    If a product is found, return it in this format:

    Product Name: [Product Name]
    Description: [Brief Description (Max 180 chars)]

    Filing Text:
    {text}
    """
    result = subprocess.run(["ollama", "chat", "--model", "llama3", "--messages", prompt], capture_output=True,
                            text=True)

    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return "Error", "Error"

    content = result.stdout
    lines = content.split("\n")

    product_name = "TBD"
    description = "TBD"

    for line in lines:
        if line.startswith("Product Name:"):
            product_name = line.replace("Product Name:", "").strip()
        elif line.startswith("Description:"):
            description = line.replace("Description:", "").strip()

    return product_name, description[:180]

# Function to save data to CSV
def save_to_csv(data, filename="LLM_Document_Analysis.csv"):
    if not data:
        print("No data to save.")
        return

    print(f"Saving data to {filename}, total rows: {len(data)}")

    with open(filename, mode="w", newline="") as file:
        writer = csv.writer(file, delimiter="|")
        writer.writerow(["Company Name", "Stock Name", "Filing Time", "New Product", "Product Description"])
        for row in data:
            writer.writerow(row)

    print(f"Data successfully saved to {filename}.")

# Main function to coordinate the process
def main():
    companies = get_top_100_companies()
    data = []

    for company in companies:
        company_name = company["title"]
        stock_name = company["ticker"]

        print(f"Processing company: {company_name} ({stock_name})")

        cik = company.get("cik", None)
        if not cik:
            print(f"Skipping {company_name}, missing CIK.")
            continue

        filing = get_latest_8k_filing(cik)
        if not filing:
            print(f"No 8-K filing found for {company_name}")
            continue

        filing_text = extract_filing_text(filing["url"])
        new_product, product_desc = query_ollama(filing_text)

        data.append([company_name, stock_name, filing["filing_time"], new_product, product_desc])

    save_to_csv(data)
    send_email("LLM Document Analysis Complete",
               "The SEC 8-K document analysis has been successfully completed and saved.")

if __name__ == "__main__":
    main()