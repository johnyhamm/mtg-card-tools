# MtG-Card-Tools

These scripts help manage your Magic: The Gathering card inventory for TCGplayer if you are primarily a manabox scanner/user

### Disclaimer

This is a work in progress. The accuracy of the output is not guaranteed, so please verify the results after running the scripts.

-----

### Setup & Installation

1. **Create a virtual environment:**

    ```bash
    python -m venv venv
    ```

2. **Activate the virtual environment:**

      * **Windows:**

        ```bash
        .\venv\Scripts\activate
        ```

      * **macOS/Linux:**

        ```bash
        source venv/bin/activate
        ```

3. **Install dependencies:**
    Install all the necessary packages from the `requirements.txt` file.

    ```bash
    pip install -r requirements.txt
    ```

-----

### How to Use

#### Option 1: Using the new modular version (recommended)

```bash
python run_converter.py
```

#### `manabox_to_tcgplayer.py` (exact matching by Scryfall ID)

This converter matches every ManaBox card by its Scryfall ID instead of by name, using [MTGJSON](https://mtgjson.com)'s free card database and its TCGplayer SKU data. There's no fuzzy matching and nothing to confirm, and you don't need to download TCGplayer's catalog first.

1. Export your collection from ManaBox as CSV and put it in this folder.
2. Run:

    ```bash
    python manabox_to_tcgplayer.py
    ```

    The first run downloads MTGJSON's database (several hundred MB) into `mtgjson_data/`. Later runs reuse it; add `--refresh` after a new set comes out.
3. Upload `tcgplayer_upload.csv` to TCGplayer. Rows that couldn't be matched go to `tcgplayer_not_found.csv` with the reason.

Options:

* `--prices your_tcgplayer_export.csv` fills in TCGplayer's market prices and product names for matched cards. Without it, the price is ManaBox's purchase price.
* Pass the ManaBox file's path if it isn't the only ManaBox CSV in the folder.

ManaBox grades like Cardmarket, so conditions are mapped as: Mint and Near Mint to Near Mint, Excellent to Lightly Played, Good and Light Played to Moderately Played, Played to Heavily Played, Poor to Damaged. Change `CONDITION_MAP` at the top of the script if you grade differently.

#### `convert_manabox_to_tcgplayer.py` / `run_converter.py`

This script converts a CSV export from Manabox to a TCGplayer-compatible format.

1. **Get your TCGplayer reference file:**

      * From your TCGplayer seller portal, go to the **Pricing** tab.
      * Click **Export Filtered CSV**.
      * Leave the options as default, but make sure **Export only from Live Inventory** is unchecked.
      * Save this file as `REFERENCE.csv` in the same folder as the script.

2. **Run the script:**

    ```bash
    python run_converter.py
    ```

3. **Follow the prompts:**

      * A window will pop up asking you to select your Manabox CSV file.
      * The script will then try to match each card. You may be prompted to confirm matches:
          * Press **Y** to confirm a match.
          * Press **N** to reject it and see the next suggestion.
          * Press **G** to give up on a card and move to the next.
      * The output will be saved as `tcgplayer_staged.csv` and any cards you gave up on will be in `tcgplayer_given_up.csv`.

#### `update_tcgplayer_prices.py`

This script updates the prices in your TCGplayer inventory CSV based on a variety of parameters that can be adjusted as needed, wanted, or desired. Always double check after running and before uploading for correct quantities, prices, etc.

1. **Run the script:**

    ```bash
    python update_tcgplayer_prices.py
    ```

2. **Select your file:**

      * A window will pop up asking you to select your TCGplayer inventory CSV.

3. **Get the output:**

      * The script will create a new file named `Updated_TCGplayer_Inventory.csv` with the updated prices.
