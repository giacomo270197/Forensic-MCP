# Investigation Report

**Generated:** 2026-03-24T10:53:01.255101Z  
**Timeline entries:** 0  
**Notes:** 7

---

## Timeline

| Time | Event | Evidence Source | Relevance |
|------|-------|----------------|-----------|

---

## Analyst Notes

# Initial Access — NTLM Brute-Force followed by RDP

**Severity:** critical  
**Recorded:** 2026-03-24T10:36:01.722631Z

---

## Summary
The attacker performed a massive NTLM/SMB brute-force attack against the Administrator account, then used the obtained credentials to establish persistent RDP access from two external IPs.

## Timeline
| Time (UTC) | Event |
|---|---|
| 2024-02-04 23:37 | NTLM brute-force begins from `36.133.110.87` (hostname: **kali**) |
| 2024-02-05 10:55 | First successful NTLM/SMB logon from `36.133.110.87` as Administrator |
| 2024-02-05 08:52 | First successful RDP (LogonType 10) from `195.21.1.97` (hostname: **ADMIN-WFH**) as Administrator |
| 2024-02-05 22:55 | Second attacker IP `185.229.66.183` (hostname: **kali**) begins RDP sessions |
| 2024-02-05 20:58 | NTLM brute-force ends |

## Key Evidence
- **200,040 failed logons** (EventID 4625, LogonType 3) from `36.133.110.87` over ~21 hours at ~174 failures/min
- Targeted account: `Administrator` (199,998 of failures)
- **0 failed RDP (LogonType 10) attempts** — credentials were obtained via NTLM, not RDP brute-force
- **1,556 successful RDP sessions** from `195.21.1.97` as Administrator (2024-02-05 to 2024-02-09)
- **44 successful RDP sessions** from `31.220.85.162` as `admin`, 2 as Administrator
- Target host: `WIN-NI9FBK23SLO.branchoffice.example.com`
- Hayabusa flagged all external RDP logons as "External Remote RDP Logon from Public IP" and "Logon *Creds in memory*"

## Attacker Infrastructure
| IP | Hostname | Role |
|---|---|---|
| `36.133.110.87` | kali | NTLM brute-force source |
| `185.229.66.183` | kali | RDP access, account creation |
| `195.21.1.97` | ADMIN-WFH | Primary RDP access (1,556 sessions) |
| `31.220.85.162` | kali | RDP access, data exfiltration pickup |


---

# Persistence — Scheduled Tasks and Privileged Account Creation

**Severity:** critical  
**Recorded:** 2026-03-24T10:36:02.537887Z

---

## Summary
The attacker established three persistence mechanisms: two malicious scheduled tasks and a new domain-privileged user account.

## Mechanism 1 — "Enterpries backup" Scheduled Task (typo intentional)
- **Created**: 2024-02-06 21:49:21 UTC by `BRANCHOFFICE\admin`
- **Action**: Executes `C:\Users\admin\Downloads\SysinternalsSuite\PsExec.exe`
- **Location**: Non-standard path (user Downloads folder) — flagged by Hayabusa rule "Scheduled Task Executed From A Suspicious Location"
- **Executed**: 2024-02-09 21:46:24 UTC (EID 200, PID 32352)
- **Updated**: 2024-02-06 22:15:47 UTC (modified after creation)
- This task is the likely delivery mechanism for Ryuk ransomware payload execution on 2024-02-07 04:46

## Mechanism 2 — "npcapwatchdog" Scheduled Task
- **Created**: 2024-02-05 23:42:52 UTC by `BRANCHOFFICE\admin`
- **Action**: `C:\Program Files\Npcap\CheckStatus.bat` runs as **SYSTEM** at startup
- **Registered via**: Hidden PowerShell command (EID 400)
- **Context**: Created alongside Npcap driver install (network capture capability for Nmap)

## Mechanism 3 — New Domain Admin Account "admin"
- **EID 4720** at 2024-02-05 23:02:00: Account `admin` (display name: "A Admin", UPN: `admin@branchoffice.example.com`) created by `Administrator`
- **EID 4732** at 2024-02-05 23:02:22: `admin` added to local **Administrators** group
- **EID 4728** at 2024-02-05 23:24:35: `admin` added to **Domain Admins**
- All actions performed during active attacker session from `185.229.66.183` (kali)
- **EID 4729** at 2024-02-09 15:08:51: `admin` account then **removed Administrator from Domain Admins and Group Policy Creator Owners** — the attacker downgraded the original admin to entrench their own account


---

# Lateral Movement — SMB, PsExec and Admin Share Enumeration

**Severity:** high  
**Recorded:** 2026-03-24T10:36:17.894245Z

---

## Summary
The attacker used PsExec and direct SMB admin-share access to move across at least 5 internal hosts in the `10.44.24.0/24` subnet.

## PsExec Lateral Movement
- **EID 4648** (11 events, 2024-02-05 23:19–23:22 UTC): `BRANCHOFFICE\admin` making explicit-credential SMB connections (port 445) to:
  - `Desktop-001.branchoffice.example.com` (10.44.24.1) at 23:19
  - `DESKTOP-005.branchoffice.example.com` (10.44.24.9) — 10 rapid-fire connections 23:22:19–23:22:42 (automated/scripted)
- **Shimcache**: `\\10.44.24.9\admin$\PSEXESVC.exe` last modified 2024-02-05 23:25:15 — PsExec's service binary was pushed to DESKTOP-005
- **PsExec.exe** and **PsExec64.exe** confirmed executed from `C:\Users\admin\Downloads\SysinternalsSuite\`

## Network Reconnaissance
- **Nmap 7.93** installed 2024-02-05 23:41:37 (confirmed executed in Shimcache)
- **Zenmap** GUI used actively: `target_list.txt` modified 2024-02-06 21:09, `recent_scans.txt` modified 2024-02-07 10:20
- **Nmap scan XML results** saved to `C:\Users\admin\Desktop\maps\`:
  - `202402062109 Intense scan on 10.44.24.1_24.xml` — full subnet scan
  - `202402071016 Intense scan on 10.44.24.1_24.xml` — repeated scan next morning

## Admin Share Browsing (Shell Bags)
The `admin_UsrClass` shell bags confirm navigation to administrative shares on multiple internal hosts:

| Host | Share | Timestamp (UTC) |
|---|---|---|
| DESKTOP-005 | `\\desktop-005\admin$` | 2024-02-05 23:22:01 |
| 10.44.24.8 | `\\10.44.24.8\c$` | 2024-02-08 19:03:46 |
| 10.44.24.1 | `\\10.44.24.1\c$` | 2024-02-08 19:04:36 |
| 10.44.24.6 | `\\10.44.24.6\c$` | 2024-02-08 19:04:54 |
| 10.44.24.7 | `\\10.44.24.7\c$` | 2024-02-08 19:05:14 |
| 10.44.24.9 | `\\10.44.24.9\admin$` | 2024-02-08 19:06:18 |

## Internal Network Logons
564 LogonType 3 (Network) logons from 5 internal IPs recorded on the server, with Administrator account network logons beginning 2024-02-06 after the initial compromise.


---

# Data Exfiltration — 694 MB Corporate File Archive via SMB

**Severity:** critical  
**Recorded:** 2026-03-24T10:36:30.204437Z

---

## Summary
The attacker compressed the entire corporate file share (~196,000 documents) into a 694 MB archive on the admin Desktop, then exfiltrated it by connecting via SMB and deleting the archive 2 minutes after pickup. A secondary archive (important.zip) was also created.

## Timeline
| Time (UTC) | Event |
|---|---|
| 2024-02-05 23:28:30 | `share.zip` (694 MB) created on admin Desktop, containing full `C:\share\` |
| 2024-02-05 23:36:06 | `share.zip` last modified (archiving complete) |
| 2024-02-06 22:12:49 | Attacker SMB logon from `31.220.85.162` (kali) |
| 2024-02-06 22:12:53 | Attacker RDP logon from `31.220.85.162`, session ends 22:12:55 (3-second "pickup" session) |
| 2024-02-06 22:14:44 | `share.zip` deleted to Recycle Bin — 2 minutes after SMB pickup |
| 2024-02-07 04:04:00 | `important.zip` (551 KB) created on admin Desktop |

## What Was Stolen
- `C:\share\` contained approximately **196,048 files** (`.docx` and `.xlsx`) belonging to numerous named user accounts including: Cole.Whitfield, Ferdinand.Strickland, Clare.Collins, Jared.Simon, Hu.Powers, and many others
- Archive size: **694,728,396 bytes (~694 MB)**

## Supporting Tools
- **7-Zip** installed on the system (LNK artefact: `C:\Users\All Users\Microsoft\Windows\Start Menu\Programs\7-Zip\7-Zip File Manager.lnk`)
- No cloud-based exfiltration tools (rclone, MEGAsync, WinSCP etc.) were found — exfiltration was performed directly over SMB

## Additional Suspicious Files on Desktop
- `dir.exe` (806 KB) and `rename.exe` (230 KB) — suspicious executables with timestomped 2016-04-01 timestamps
- Nmap scan XML files in `C:\Users\admin\Desktop\maps\`


---

# Impact — Ryuk Ransomware Deployment and Privilege Abuse

**Severity:** critical  
**Recorded:** 2026-03-24T10:36:42.748923Z

---

## Summary
The attacker deployed Ryuk ransomware via a scheduled task, distributed ransom-staging files across user share directories, probed Credential Manager, and abused Domain Admin privileges to entrench access and downgrade the legitimate administrator account.

## Ryuk Ransomware Activity
- **RyukReadMe.lnk** in Recent Items: 2024-02-06 20:53:29 UTC — the admin account opened a Ryuk ransom note at this time
- **RyukReadMe.txt** (1,912 bytes) created on admin Desktop: 2024-02-07 04:46:00 UTC — with **no interactive logon active**, consistent with scheduled task execution
- **important.zip** (551 KB) created 2024-02-07 04:04:00 UTC — likely containing data staged for ransom leverage
- **Credential Manager probed** at 2024-02-07 04:10:02 by both admin and Administrator sessions — immediately before ransomware dropped the note
- No .RYK encrypted file extensions found on this host — ransomware encryption targeted **remote shares** accessed via lateral movement, not the server itself

## Ransomware Staging Files
- **158 double-extension files** (`view.pdf.docx` / `view.pdf.xlsx`) distributed across 122 user share directories in `C:\share\<username>\Documents\`
- 15 files created during the intrusion window (2024-02-05 to 2024-02-08)
- Pattern consistent with Ryuk ransomware dropping lure/marker files in share directories

## Delivery Mechanism
The **"Enterpries backup" scheduled task** (created 2024-02-06 21:49 by `BRANCHOFFICE\admin`) is the most likely delivery vehicle:
- Executes PsExec.exe from `C:\Users\admin\Downloads\SysinternalsSuite\`
- Last updated 2024-02-06 22:15:47 (shortly before the overnight execution)
- Confirmed executed 2024-02-09 21:46:24

## Privilege Abuse
| Time (UTC) | Event |
|---|---|
| 2024-02-05 23:24:35 | `admin` added itself to **Domain Admins** |
| 2024-02-09 15:08:51 | `admin` **removed Administrator** from Domain Admins and Group Policy Creator Owners |

The removal of `Administrator` from privileged groups on 2024-02-09 represents a deliberate attempt to prevent legitimate admin recovery and maintain sole control over the domain.

## Pre-existing Weakness
Windows Defender Real-time Protection was **already disabled** as of 2023-09-24 (before the attack), providing no AV detection during the intrusion.


---

# Ryuk Binaries — dir.exe and rename.exe (Timestomped)

**Severity:** critical  
**Recorded:** 2026-03-24T10:50:31.669773Z

---

## Summary
Two timestomped 32-bit PE executables were found on the admin Desktop, dropped simultaneously by the attacker on 2024-02-06 at 20:13:40 UTC. Their names mimic legitimate Windows shell commands to evade casual inspection. Size, naming pattern, and forensic indicators are consistent with Ryuk ransomware (encryptor + companion killer binary).

## Files

| Property | `dir.exe` | `rename.exe` |
|---|---|---|
| **Path** | `C:\Users\admin\Desktop\dir.exe` | `C:\Users\admin\Desktop\rename.exe` |
| **SHA1** | `d1c62ac62e68875085b62fa651fb17d4d7313887` | `39b6d40906c7f7f080e6befa93324dddadcbd9fa` |
| **Size** | 806,912 bytes (~806 KB) | 230,912 bytes (~230 KB) |
| **Type** | 32-bit PE, non-OS component | 32-bit PE, non-OS component |
| **Actual drop time** (`$FN`) | 2024-02-06 20:13:40 UTC | 2024-02-06 20:13:40 UTC |
| **Fake timestamp** (`$SI`) | 2016-04-01 00:00:00 (round date) | 2016-03-24 00:00:00 (round date) |
| **Compile date** (Amcache) | 2016-01-30 02:56:43 | 2016-01-09 12:11:59 |
| **Zone.Identifier** | None | None |
| **Shimcache Executed** | No (see note) | No (see note) |
| **Still on disk** | Yes (InUse=1) | Yes (InUse=1) |

## Timestomping
Both files have `$STANDARD_INFO` timestamps set to suspiciously round 2016 dates — a deliberate anti-forensic technique. The `$FILE_NAME` timestamps (harder to forge) reveal the true placement time: **2024-02-06 20:13:40 UTC**, during the attacker's active session.

## No Zone.Identifier
Neither file has a Zone.Identifier alternate data stream, meaning they were **not downloaded via a browser**. They were copied or transferred directly onto the system — consistent with being moved from the attacker's machine via the active RDP/SMB session.

## Shimcache Execution Note
Shimcache records `Executed=No` for both files. This does not rule out execution — binaries spawned via PsExec, services, or scheduled tasks can bypass the shimcache execution flag. Given that `RyukReadMe.txt` appeared at 04:46 UTC on 2024-02-07 with no interactive session active, execution via the "Enterpries backup" scheduled task (PsExec) is the most likely delivery path.

## Ryuk Attribution
Ryuk ransomware typically ships as two components:
- **Main encryptor** (~800 KB range) — `dir.exe` matches this profile
- **Companion killer** (~200–300 KB) — terminates AV services and processes before encryption; `rename.exe` matches this profile

Both SHA1 hashes should be submitted to VirusTotal or a threat intelligence platform for definitive attribution.

## Recommended Threat Intel Lookups
```
d1c62ac62e68875085b62fa651fb17d4d7313887   dir.exe    (probable Ryuk encryptor)
39b6d40906c7f7f080e6befa93324dddadcbd9fa   rename.exe (probable Ryuk killer/dropper)
```


---

# Indicators of Compromise (IOCs)

**Severity:** critical  
**Recorded:** 2026-03-24T10:52:58.375380Z

---

## Network Indicators

### Attacker IP Addresses
| IP | Hostname | Activity |
|---|---|---|
| `36.133.110.87` | kali | NTLM/SMB brute-force (200,040 failures, 2024-02-04 to 2024-02-05) |
| `185.229.66.183` | kali | RDP access; created `admin` account and added to Domain Admins |
| `195.21.1.97` | ADMIN-WFH | Primary RDP access (1,556 sessions as Administrator, 2024-02-05 to 2024-02-09) |
| `31.220.85.162` | kali | RDP access; SMB exfiltration pickup of share.zip (2024-02-06 22:12) |

---

## File Hashes

### Malicious Executables (SHA1)
| SHA1 | Filename | Size | Description |
|---|---|---|---|
| `d1c62ac62e68875085b62fa651fb17d4d7313887` | `dir.exe` | 806,912 B | Probable Ryuk encryptor — timestomped, 32-bit PE |
| `39b6d40906c7f7f080e6befa93324dddadcbd9fa` | `rename.exe` | 230,912 B | Probable Ryuk killer/dropper — timestomped, 32-bit PE |

### Attacker Tools (SHA1)
| SHA1 | Filename | Description |
|---|---|---|
| `3e2272b916da4be3c120d17490423230ab62c174` | `PsExec.exe` | Sysinternals PsExec — used for lateral movement |
| `0098c79e1404b4399bf0e686d88dbf052269a302` | `PsExec64.exe` | Sysinternals PsExec 64-bit — used for lateral movement |

---

## File System Indicators

### Ransomware Artefacts
| Path | Description |
|---|---|
| `C:\Users\admin\Desktop\dir.exe` | Probable Ryuk encryptor (timestomped to 2016-04-01, actually dropped 2024-02-06 20:13:40) |
| `C:\Users\admin\Desktop\rename.exe` | Probable Ryuk killer (timestomped to 2016-03-24, actually dropped 2024-02-06 20:13:40) |
| `C:\Users\admin\Desktop\RyukReadMe.txt` | Ryuk ransom note (created 2024-02-07 04:46:00) |
| `C:\Users\admin\Desktop\important.zip` | Secondary data archive (551 KB, created 2024-02-07 04:04:00) |
| `C:\share\*\Documents\view.pdf.docx` | Ryuk staging file — 158 instances across 122 user share directories |
| `C:\share\*\Documents\view.pdf.xlsx` | Ryuk staging file — double-extension variant |

### Exfiltration Artefacts
| Path | Description |
|---|---|
| `C:\Users\admin\Desktop\share.zip` | 694 MB archive of full C:\share\ (~196,000 files) — exfiltrated 2024-02-06, deleted after pickup |

### Attacker Tooling
| Path | Description |
|---|---|
| `C:\Users\admin\Downloads\SysinternalsSuite\PsExec.exe` | PsExec — confirmed executed 2024-02-05 23:14 |
| `C:\Users\admin\Downloads\SysinternalsSuite\PsExec64.exe` | PsExec64 — confirmed executed 2024-02-05 23:14 |
| `C:\Users\admin\Downloads\nmap-7.93-setup.exe` | Nmap installer — executed 2024-02-05 23:41 |
| `C:\Users\admin\Desktop\maps\202402062109 Intense scan on 10.44.24.1_24.xml` | Nmap scan result — full subnet scan 2024-02-06 21:09 |
| `C:\Users\admin\Desktop\maps\202402071016 Intense scan on 10.44.24.1_24.xml` | Nmap scan result — repeated subnet scan 2024-02-07 10:16 |
| `C:\Users\admin\.zenmap\target_list.txt` | Zenmap saved scan targets |
| `C:\Users\admin\.zenmap\zenmap.db` | Zenmap scan results database |
| `C:\Users\admin\Downloads\SysinternalsSuite.zip` | SysinternalsSuite archive — downloaded then deleted 2024-02-05 23:14 |

### Persistence Artefacts
| Path | Description |
|---|---|
| `C:\Windows\System32\Tasks\Enterpries backup` | Malicious scheduled task (misspelled) — executes PsExec from Downloads |
| `C:\Windows\System32\Tasks\npcapwatchdog` | Suspicious scheduled task — runs BAT as SYSTEM at startup |
| `C:\Program Files\Npcap\CheckStatus.bat` | Script executed by npcapwatchdog task as SYSTEM |

---

## Account Indicators

### Attacker-Created Account
| Attribute | Value |
|---|---|
| **Username** | `admin` |
| **Display name** | A Admin |
| **UPN** | `admin@branchoffice.example.com` |
| **SID** | `S-1-5-21-1057484085-1795310446-2370380301-2611` |
| **Created** | 2024-02-05 23:02:00 UTC by `Administrator` |
| **Groups added** | Local Administrators (23:02:22), Domain Admins (23:24:35) |
| **Abuse** | Removed `Administrator` from Domain Admins and Group Policy Creator Owners on 2024-02-09 15:08:51 |

---

## Scheduled Task Indicators

| Task name | Created | Action | Run as |
|---|---|---|---|
| `\Enterpries backup` | 2024-02-06 21:49:21 | `C:\Users\admin\Downloads\SysinternalsSuite\PsExec.exe` | BRANCHOFFICE\admin |
| `\npcapwatchdog` | 2024-02-05 23:42:52 | `C:\Program Files\Npcap\CheckStatus.bat` | SYSTEM |

---

## Lateral Movement Indicators

### Hosts Accessed via Admin Shares
| Internal IP | Hostname | Share accessed | First seen (UTC) |
|---|---|---|---|
| `10.44.24.9` | DESKTOP-005 | `admin$` | 2024-02-05 23:22:01 |
| `10.44.24.1` | Desktop-001 | `c$` | 2024-02-08 19:04:36 |
| `10.44.24.6` | — | `c$` | 2024-02-08 19:04:54 |
| `10.44.24.7` | — | `c$` | 2024-02-08 19:05:14 |
| `10.44.24.8` | — | `c$` | 2024-02-08 19:03:46 |

### PsExec Remote Execution
| Indicator | Value |
|---|---|
| Remote service binary | `\\10.44.24.9\admin$\PSEXESVC.exe` |
| First pushed | 2024-02-05 23:25:15 UTC |
| Target host | DESKTOP-005 (`10.44.24.9`) |

---

## Event Log Indicators (Key Event IDs)

| Event ID | Channel | Description | Timestamp (UTC) |
|---|---|---|---|
| 4625 (×200,040) | Security | Failed NTLM logons from `36.133.110.87` | 2024-02-04 23:37 – 2024-02-05 20:58 |
| 4624 (×1,556) | Security | Successful RDP logons from `195.21.1.97` as Administrator | 2024-02-05 – 2024-02-09 |
| 4720 | Security | Account `admin` created by Administrator | 2024-02-05 23:02:00 |
| 4732 | Security | `admin` added to local Administrators | 2024-02-05 23:02:22 |
| 4728 | Security | `admin` added to Domain Admins | 2024-02-05 23:24:35 |
| 4648 (×11) | Security | Explicit credential logons to Desktop-001 / DESKTOP-005 | 2024-02-05 23:19–23:22 |
| 106 | Task Scheduler | Task `\Enterpries backup` created | 2024-02-06 21:49:21 |
| 106 | Task Scheduler | Task `\npcapwatchdog` created | 2024-02-05 23:42:52 |
| 7045 | System | Npcap Packet Driver installed | 2024-02-05 23:42:42 |
| 200 | Task Scheduler | Task `\Enterpries backup` executed PsExec.exe | 2024-02-09 21:46:24 |
| 4729 | Security | `Administrator` removed from Domain Admins by `admin` | 2024-02-09 15:08:51 |

---

## Ransom Note Content Indicator
- **Filename:** `RyukReadMe.txt`
- **Size:** 1,912 bytes
- **Location:** `C:\Users\admin\Desktop\`
- **File name pattern also found as LNK:** `C:\Users\admin\AppData\Roaming\Microsoft\Windows\Recent\RyukReadMe.lnk` (2024-02-06 20:53:29)


---
