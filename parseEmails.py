import imaplib
import email
import json
import os
from email.header import decode_header
import re
import requests
import time
import sensitive
from bs4 import BeautifulSoup
from datetime import datetime

# Gmail credentials and folder name
USERNAME = sensitive.USERNAME
PASSWORD = sensitive.PASSWORD
HOME_ASSISTANT_WEBHOOK_URL = sensitive.WEBHOOK
BILL_NAMES = sensitive.BILL_NAMES
BILL_NAMES_LIST = list(BILL_NAMES.keys())
FOLDER = "Bills"
BILL_JSON_FILE = sensitive.EMAIL_JSON
ID_JSON_FILE = sensitive.ID_JSON

# Used to track message id's for already processed emails
def add_id_entry(message_id):
    with open(ID_JSON_FILE, 'r') as f:
        current_data = json.load(f) #Get current json list
    
    current_data.append({"id": message_id})
    with open(ID_JSON_FILE, 'w') as f:
        json.dump(current_data, f, indent=4)
    return None

# Checks whether message id has already been processed
def id_added(message_id):
    with open(ID_JSON_FILE, 'r') as f:
        current_data = json.load(f) #Get current json list
    
    for entry in current_data:
        if(entry["id"] == message_id):
            return True
    return False

# Add processed bills to json file
def add_email_entry(sender, due_date):
    with open(BILL_JSON_FILE, 'r') as f:
        current_data = json.load(f) #Get current json list
    
    current_data.append({"email": sender, "due_date": due_date})
    with open(BILL_JSON_FILE, 'w') as f:
        json.dump(current_data, f, indent=4)
    
    return None

# Checks whether a bill has already been processed
def bill_added(sender, due_date):
    with open(BILL_JSON_FILE, 'r') as f:
        current_data = json.load(f) #Get current json list
    
    for entry in current_data:
        if(entry["email"]== sender and entry["due_date"] == due_date):
            return True
    return False

# Converts dates in written format to mm/dd/yyyy format
def convert_date(date_str):
    # Parse the input date string
    try:
        date_obj = datetime.strptime(date_str, "%B %d, %Y")
        # Convert to MM/DD/YY format
        return date_obj.strftime("%m/%d/%y")
    except ValueError:
        return None  # Return None if the input date is not in the correct format

# Set up IMAP connection
def connect_to_gmail():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(USERNAME, PASSWORD)
    return mail

# Search for emails in the "Bills" folder
def check_for_new_emails(mail):
    mail.select(FOLDER)
    status, messages = mail.search(None, "UNSEEN")  # Search only unread messages
    
    email_ids = messages[0].split()
    new_emails = []
    for email_id in email_ids[::-1]:  # Check latest first
        status, msg_data = mail.fetch(email_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                message_id = msg.get("Message-ID")
                if not id_added(message_id):
                    new_emails.append((email_id, msg, message_id))
    return new_emails

# Scrape email body for bill amount
def extract_bill_amount(email_body, sender):
    # Use BeautifulSoup to strip HTML tags
    soup = BeautifulSoup(email_body, "html.parser")
    plain_text = soup.get_text()
    if(sender == BILL_NAMES_LIST[0]): #Checks if message is water bill. Water bill does not contain a $
         pattern = r"Amount Due\s+([0-9]+(?:\.[0-9]{2})?)"
    elif(sender == BILL_NAMES_LIST[3]): #checks if message is gas bill
        pattern = r"Amount Due:\s*\$([0-9]+(?:\.[0-9]{2})?)"
    else:
        pattern = r"\$([0-9]+(?:\.[0-9]{2})?)"
    match = re.search(pattern, plain_text)
    if match:
        return match.group(1)
    return None

def extract_due_date(email_body, sender):
    # Use BeautifulSoup to strip HTML tags
    soup = BeautifulSoup(email_body, "html.parser")
    plain_text = soup.get_text()
    if(sender != BILL_NAMES_LIST[1] and sender != BILL_NAMES_LIST[3]):
        if(sender == BILL_NAMES_LIST[0]):
            pattern = r"Due Date\s*(\d{2}/\d{2}/\d{2})"
        elif(sender == BILL_NAMES_LIST[2]):
            pattern = r"due on\s*(\d{2}/\d{2}/\d{4})"
        elif(sender == BILL_NAMES_LIST[4]):
            pattern = r"Due Date:\s*(\d{2}/\d{2}/\d{4})"
        match = re.search(pattern, plain_text)
        return match.group(1)
    elif(sender == BILL_NAMES_LIST[1]): #checks if current bill is spectrum
        pattern = r'Auto Pay Date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})'
        match = re.search(pattern, plain_text)
        full_date = f"{match.group(1)}"
        final_date = convert_date(full_date)
        return final_date
    elif(sender == BILL_NAMES_LIST[3]): #Checks if current bill is gas bill
        pattern = r'Due Date:\s*([A-Za-z]+)\.?\s*(\d{1,2}),\s*(\d{4})'
        match = re.search(pattern, plain_text)
        final_date = f"{match.group(1)} {match.group(2)}, {match.group(3)}"
        return final_date

# Send data to Home Assistant
def send_to_home_assistant(amount, due_date, bill_name):
    split = round(float(amount) / 4.0, 2)
    payload = {"amount": amount, "due_date": due_date, "bill_name": bill_name, "split": split}
    try:
        response = requests.post(HOME_ASSISTANT_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        print(f"Sent amount webhook request to Home Assistant.")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send data: {e}")
    
    time.sleep(2) # Short delay to prevent flooding the webhook

# Process email parts for bill amount
def process_email_parts(msg, message_id, sender):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            charset = part.get_content_charset()
            
            if content_type in ["text/plain", "text/html"]:
                payload = part.get_payload(decode=True)
                email_body = decode_email_body(payload, charset)
                
                if email_body:
                    bill_amount = extract_bill_amount(email_body, sender)
                    due_date = extract_due_date(email_body, sender)
                    if not bill_added(sender, due_date): # Check whether a notification has already been sent about this bill
                        print(f"Found due date: {due_date}")
                        if bill_amount:
                            print(f"Found bill amount: {bill_amount}")
                            add_email_entry(sender, due_date)
                            send_to_home_assistant(bill_amount, due_date, BILL_NAMES.get(sender))
                            add_id_entry(message_id)
                            return True
                    else:
                        print("Bill already notified.")
                        return True
    else:
        # Handle non-multipart email
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset()
        email_body = decode_email_body(payload, charset)

        if email_body:
            bill_amount = extract_bill_amount(email_body, sender)
            due_date = extract_due_date(email_body, sender)
            if not bill_added(sender, due_date): # Check whether a notification has already been sent about this bill
                print(f"Found due date: {due_date}")
                if bill_amount:
                    print(f"Found bill amount: {bill_amount}")
                    add_email_entry(sender, due_date)
                    send_to_home_assistant(bill_amount, due_date, BILL_NAMES.get(sender))
                    add_id_entry(message_id)
                    return True
            else:
                print("BIll already notified.")
                return True
    return False

# Decode email body with charset handling and fallback
def decode_email_body(payload, charset):
    try:
        return payload.decode(charset or "utf-8")
    except (UnicodeDecodeError, LookupError):
        try:
            return payload.decode("ISO-8859-1")  # Fallback to Latin-1
        except UnicodeDecodeError as e:
            print(f"Failed to decode email body: {e}")
            return None

# Monitor the "Bills" folder
def monitor_bills_folder():
    mail = connect_to_gmail()

    while True:
        try:
            new_emails = check_for_new_emails(mail)
            if new_emails:
                for email_id, msg, message_id in new_emails:
                    email_subject = decode_header(msg["Subject"])[0][0]
                    email_from = decode_header(msg.get("From"))[0][0]

                    print(f"New email from: {email_from}, subject: {email_subject}")

                    # Process email parts and look for bill amount
                    processed = process_email_parts(msg, message_id, email_from)
                    if not processed:
                        print("No bill amount found in the email.")
                    
        except Exception as e:
            print(f"Error: {e}")

        # Sleep for a bit before checking again
        time.sleep(10)

if __name__ == "__main__":
    monitor_bills_folder()