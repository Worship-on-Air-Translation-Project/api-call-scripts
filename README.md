# Translator App Setup

## How to Run

1. Download the ZIP file of this repository from GitHub and unzip it.

2. Open your **terminal** and change into the unzipped project folder. Example:

```bash
cd your-unzipped-folder-name
```

3. **Configure your environment variables:**

   - Create `.env` file:

   ```bash
   touch .env
   ```
	
   - To show the hidden files in Finder, press Cmd + Shift + . -> hidden files (like .env) will appear. Press again to hide them.

 
   - Open `.env` in a text editor and add your Azure credentials:

   ```env
   # Azure Translator API Key
   TRANSLATOR_KEY=YOUR_TRANSLATOR_KEY_HERE
   TRANSLATOR_REGION=global

   # Azure Speech API Key
   SPEECH_KEY=YOUR_SPEECH_KEY_HERE
   SPEECH_REGION=eastus
   ```

   Make sure to save the file before running the setup script.

4. Make the setup script executable:

```bash
chmod +x setup_and_run.sh
```

5. Run the script to start the server and open the website:

```bash
./setup_and_run.sh
```
