# Deployment Guide - Streamlit Community Cloud

This guide explains how to deploy your "Oikotie Scraper" for free so you can show it to your client.

> [!NOTE]
> Streamlit Community Cloud is a free hosting service perfect for Proof of Concept (POC) apps.

## Prerequisites
1.  A GitHub Account ([github.com](https://github.com/)).
2.  A Streamlit Account ([share.streamlit.io](https://share.streamlit.io/)).

## Step 1: Push Code to GitHub
You need to create a repository and push your code there.

1.  **Create a New Repository** on GitHub (e.g., `oikotie-scraper`).
2.  **Upload your files**:
    - Upload the contents of your `oikotie_scraper` folder (`app.py`, `scraper.py`, `requirements.txt`, `packages.txt`).
    - *Alternatively, use git commands if you are familiar with them.*

## Step 2: Deploy on Streamlit Cloud
1.  Log in to [Streamlit Community Cloud](https://share.streamlit.io/).
2.  Click **"New app"**.
3.  Select your GitHub repository (`oikotie-scraper`).
4.  Select the **Main file path**: `app.py`.
5.  Click **"Deploy!"**.

## Step 3: Wait for Installation
- Streamlit will read `requirements.txt` and `packages.txt` to install dependencies.
- It might take 2-3 minutes to start the first time as it installs the browser.
- Once running, you will get a public URL (e.g., `https://oikotie-scraper.streamlit.app`) to share with your client.

> [!WARNING]
> **Blocking Risk**: Oikotie.fi might block traffic from data centers (like Streamlit Cloud).
> If the deployed app fails to fetch data (returns 0 links), it means the IP is blocked.
> **Alternative**: If this happens, use **ngrok** to host it from your laptop temporarily.

## Alternative: Local Hosting with ngrok (No IP Blocking)
If the cloud version is blocked, you can "tunnel" your local running app to the internet.
1.  Run the app locally: `streamlit run app.py`
2.  Install ngrok: `brew install ngrok/ngrok/ngrok` (or download from website).
3.  Run: `ngrok http 8501`
4.  Share the generated `https://....ngrok-free.app` link with your client.
