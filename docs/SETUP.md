# Setup & Operator Guide — Convenience Store POS

Windows desktop Point of Sale built with **Python + PySide6 + MySQL (XAMPP)**.

> Current stage: **v1.0.0 — Phases 0–12 complete**. Store PC installation and the daily routine:
> **`MANUAL.md`** (project root).

---

## First-time setup (do these once, in order)

All commands are typed in **Windows PowerShell**.
To open it *inside the project folder*: open the `convenience_store_pos` folder in
File Explorer → click the address bar → type `powershell` → press **Enter**.

The commands below assume the folder is `C:\pos\convenience_store_pos`. If you put it
elsewhere, that's fine — just open PowerShell inside it as described.

### Step 1 — Start MySQL
1. Open **XAMPP Control Panel**.
2. Click **Start** next to **MySQL**. Wait until its name turns green.
   (Apache is **not** needed.)

### Step 2 — Check your computer (read-only)
```powershell
python scripts\check_environment.py
```
- If it asks *"Try logging in to MySQL?"*, type `y`, username `root`, then the root
  password (just press **Enter** if root has no password — fresh XAMPP installs usually don't).
- It saves `scripts\environment_report.txt`. **Keep it for troubleshooting.**

If PowerShell says `python` is not recognized or opens the Microsoft Store, use `py`
instead of `python` in this step only.

### Step 3 — Create a private Python environment and install packages
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
This keeps the POS's packages separate from anything else on the computer.
From now on, always run things with `.\.venv\Scripts\python.exe`.

### Step 4 — Create the POS database account (recommended)
```powershell
.\.venv\Scripts\python.exe scripts\create_app_user.py
```
Press **Enter** to accept defaults, give the **root** password (Enter if none), then
choose a new password for the `pos_app` account. This creates `.env` for you.
`pos_app` can only access the POS database, not your other databases.

### Step 5 — Create / update the POS database
```powershell
.\.venv\Scripts\python.exe scripts\setup_database.py
```
Safe to run any time — it only adds what's missing and never deletes data.
To preview without changing anything: add `--status`.

### Step 6 — Start the POS
```powershell
.\.venv\Scripts\python.exe main.py
```
Or simply double-click **`Start POS.bat`** in the project folder (no black window).

The first time, it asks you to **create the administrator account** (usually the owner).
After that it shows the login screen.

## Updating to a new version
1. Close the POS.
2. Copy the new files over the project folder (replace files). Your `.env`, `.venv`, `logs` and `backups` are kept.
3. Run `.\.venv\Scripts\python.exe scripts\setup_database.py` — it applies any new database updates safely.
4. Run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` — installs any new package
   (version 0.9.0 added `openpyxl` for Excel reports). Safe to repeat.
5. Start the POS.

## Using the POS (so far)
| Task | How |
|---|---|
| Add a staff account | **Users → + Add user** (Ctrl+N). Give them the temporary password shown; they choose their own at first login. |
| Someone forgot their password | **Users →** select them **→ Reset password**. Also unlocks a locked account. |
| Someone left | **Users →** select **→ Disable**. Their past records stay. |
| **Sell** | **Checkout**: scan each item (or type part of the name + Enter). `3*` before a scan adds 3. **F12** (or Space with the box empty) to pay. |
| Change quantity / remove | ↑ ↓ to choose the line, then **+ / −**, **F4** (type quantity) or **Del**. Cashiers need a manager to reduce or remove. |
| Discount | **F6** this item, **F7** whole sale. Pick the reason (Senior citizen, PWD, Promo…). Cashiers need a manager. |
| Customer pays two ways | In the payment window: enter the GCash/Card part, **Add another payment**, then the cash. |
| Customer steps away | **F8 Hold**, give it a name. **F9 Recall** to continue it. |
| Print / reprint a receipt | Prints automatically after each sale. **P** on the sale-complete screen for another copy, or **Sales history** → open the sale → **Receipt…** (copies say REPRINT). |
| Look up a past sale | **Sales history** → search by date, sale number or item → double-click. |
| Payment methods (GCash, Maya…) | **Store settings → Payment methods**. |
| Add a product | **Products → + Add product** (Ctrl+N), or scan an unknown barcode into the search box and choose *Add product*. |
| Find a product | **Products**: type part of the name/brand, or scan the barcode (F3 jumps to the search box). |
| Change a price | **Products →** select **→ Edit**. Old prices are kept in **Price history**. |
| Stop selling an item | **Products →** select **→ Deactivate** (history is kept). |
| Categories, brands, units | **Categories & brands** (tabs). |
| Store name, address, currency | **Store settings** (Ctrl+S saves). |
| Who did what | **Audit log** — search by name/action and date. |
| **Start of the day / shift** | **My shift → Open shift…**, count the cash in the drawer. The checkout works only after this. |
| Add coins / take cash to the safe | **My shift → Cash in… / Cash out…** (cashiers need a manager). |
| Pay something from the drawer (ice, delivery) | **My shift → Expense from drawer…**. Other expenses (rent, electricity): **Expenses → + Add expense**. |
| **End of shift** | **My shift → Close shift…**, type how many of each bill/coin. The POS then shows OVER / SHORT / Exact. **Print report** for the shift report. |
| See all shifts / close a forgotten shift | **Shifts** (managers): pick the dates → **Show**, select a shift → **Open** or **Close this shift…**. |
| Stock on hand, low stock | **Inventory** (tick *Low stock only*). **Movements…** shows every change; **Adjust stock…** for damaged/lost/found. |
| Enter opening stock / count the shelves | **Stock count**: count, save, **Finish** to set stock to the counted numbers. |
| A delivery arrives | **Receive stock**: supplier (optional), scan items, quantity and cost, **Save**. Tick *Paid with cash from my drawer* if you paid with drawer cash. |
| Suppliers | **Suppliers** (name, phone, note). |
| How did today go? | **Dashboard** shows today's sales, profit, low stock and open shifts. |
| Day's sales, profit and expenses | **Daily report**: choose the day (◀ ▶ or the calendar). **Save to Excel…** keeps a copy you can print. |
| Back up now / see last backup | **Store settings → Backups → Back up now** (also automatic once a day). |
| Restore a backup | Close the POS, then in Command Prompt: `.venv\Scripts\python.exe scripts\restore_backup.py --restore` (or `POS Tools.exe` → 7). |
| Build the store PC program | Command Prompt in the project folder: `build_exe.bat`, then copy `dist\ConvenienceStorePOS` (see `MANUAL.md` in the project root). |
| Log out | **Log out** button or **Ctrl+L**. |

Roles: **Administrator** (everything), **Manager** (everything except users and settings),
**Cashier** (checkout, own shift), **Inventory Staff** (products and stock), **Purchasing Staff**
(suppliers, purchase orders, receiving). Five wrong passwords lock an account for 5 minutes.

---

## Receipt printer (thermal) setup
1. Install the printer's **Windows driver** (from the CD/USB stick or the maker's website) and check it
   appears in **Windows Settings → Bluetooth & devices → Printers & scanners**.
2. In the POS: **Store settings → Receipt printer** → choose it, choose **58 mm** or **80 mm**, click
   **Print test receipt**. The row of numbers `1234567890…` must fit on one line; if not, change the width.
3. Click **Save settings**.
4. A cash drawer connected to the printer is opened by the **printer driver** (look for "Cash drawer" /
   "Open drawer before printing" in the printer's Printing preferences in Windows).

## Barcode scanner
USB scanners work like a keyboard: they type the code and press **Enter**. Test by clicking the
**Checkout** scan box and scanning. If nothing is added, the scanner may be set to send *Tab* instead of
*Enter* — scan the "Add CR / Enter suffix" setup barcode in the scanner's manual.

## Running the automated tests
```powershell
.\.venv\Scripts\python.exe -m pytest
```
Database tests are skipped unless you provide a MySQL account for testing:
```powershell
$env:POS_TEST_DB_USER="root"; $env:POS_TEST_DB_PASSWORD=""
.\.venv\Scripts\python.exe -m pytest
```
They create a temporary database named `pos_pytest_xxxxx` and delete **only that one**.

## Troubleshooting
| What you see | What to do |
|---|---|
| "Cannot reach the database" | XAMPP → Start MySQL. If it won't start, port 3306 may be used by another MySQL; ask your support person. |
| "username or password is wrong" | Re-run Step 4. Forgot the XAMPP root password? Stop MySQL in XAMPP, double-click `scripts\reset_xampp_root_password.bat`, then Start MySQL. |
| XAMPP: "MySQL shutdown unexpectedly" + log says `Bind on TCP/IP port` | Another MySQL (e.g. the `MySQL80` service) is using port 3306. In an **administrator** Command Prompt: `net stop MySQL80` then `sc config MySQL80 start= demand`. |
| "POS database does not exist yet" | Run Step 5. |
| "database update(s) are waiting" | Run Step 5. |
| `STOPPED: database ... already exists` | A non-POS database has that name. Nothing was changed; ask your support person. |
| Anything else | Send `logs\pos.log` to your support person (it never contains passwords). |

## Files you must keep private
- `.env` — contains the database password. Never email or upload it.
