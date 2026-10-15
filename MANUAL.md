# Sample Corner Store POS — Manual

Two parts: **A. Installing on the store PC** (once) and **B. Daily use** (every day).
Screen-by-screen help is in `docs/SETUP.md` → "Using the POS".

---

## A. Installing on the store PC (no Python needed)

You need: the `ConvenienceStorePOS` folder (made on the development PC with `build_exe.bat`, found in
`dist\ConvenienceStorePOS`) and XAMPP.

1. **Install XAMPP** from apachefriends.org (default folder `C:\xampp`).
   Open **XAMPP Control Panel**, tick **Svc** next to MySQL (so MySQL starts by itself with Windows),
   then click **Start** next to MySQL.
   - If MySQL will not start with "port 3306 in use", another MySQL is installed. In Command Prompt
     run `sc query MySQL80`; if it is running, stop it and set it to Manual in Windows Services.
2. **Copy the folder** `ConvenienceStorePOS` to `C:\ConvenienceStorePOS`.
   Do not put it in `C:\Program Files` (the POS writes its logs and backups next to itself).
3. **Antivirus:** add `C:\ConvenienceStorePOS` as an exception in your antivirus. Some antivirus programs
   wrongly delete programs made with PyInstaller. Restart the PC if a file was blocked.
4. Double-click **`POS Tools.exe`** and choose, in this order:
   - **1** Check this computer (read-only; shows if XAMPP and MySQL are found).
   - **2** Create the POS database account. Type the database name (e.g. `convenience_store_pos`), the XAMPP
     `root` password (empty on a fresh XAMPP: just press Enter), and a new password for `pos_app`.
     This writes the `.env` file. Keep `.env` private — it holds the password.
   - **3** Create / update the POS database.
5. Double-click **`ConvenienceStorePOS.exe`**. The first time, it asks you to create the Administrator account.
   Right-click `ConvenienceStorePOS.exe` → **Send to → Desktop (create shortcut)** for a desktop icon.
6. Store settings: store name, address, receipt printer (Print test receipt), payment methods.
7. Enter your products, then the opening stock with **Stock count**.

### Moving data from another PC
On the old PC: `POS Tools.exe` → **5** (or **Store settings → Back up now**). Copy the newest file from
its `backups` folder to the new PC's `C:\ConvenienceStorePOS\backups`. On the new PC, after step 4:
`POS Tools.exe` → **7**, choose that file, type `RESTORE`, then **3** again.

### Updating to a new version
1. Close the POS. Make a backup (`POS Tools.exe` → **5**).
2. Copy the new `ConvenienceStorePOS` folder over the old one (replace files). Your `.env`, `logs` and
   `backups` stay.
3. `POS Tools.exe` → **3** (applies database updates), then start the POS.

---

## B. Daily use

**Opening (cashier)**
1. Start MySQL in XAMPP if it is not running, then open the POS and log in.
   (The POS makes the day's backup by itself when it starts.)
2. **My shift → Open shift…**: count the cash in the drawer and type it.

**During the day**
- Sell in **Checkout**: scan items, **F12** to pay. Receipts print by themselves.
- Coins added / cash taken to the safe: **My shift → Cash in / Cash out** (manager approves).
- Ice, delivery fee and other small costs paid from the drawer: **My shift → Expense from drawer**.
- A delivery arrives: **Receive stock** (tick *Paid with cash from my drawer* if paid from the drawer).

**Closing (cashier)**
1. **My shift → Close shift…**: count every bill and coin. The POS then shows OVER / SHORT / Exact.
2. **Print report** and keep it with the cash.

**Owner, end of the day**
- **Daily report**: sales, profit, expenses and each shift's over/short. **Save to Excel…** to keep it.
- **Dashboard**: today's sales, low-stock items and who still has a shift open.
- Once a week: copy the `backups` folder to a USB stick or online storage.

**If something goes wrong**
- "Cannot reach the database": start MySQL in XAMPP Control Panel, then click *Check connection again*.
- Restore a backup: close the POS on every PC, `POS Tools.exe` → **7**. Your current data is saved
  first (a "before-restore" backup), so a wrong restore can be undone.
- Any other error: the details are in `logs\pos.log`.
