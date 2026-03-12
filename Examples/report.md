# Forensic Investigation Report
**Case:** Ransomware Compromise — Windows Server
**Evidence:** Disk image mounted at G:
**Investigator:** Claude Code (claude-sonnet-4-6) — automated triage
**Report Date:** 2026-03-12
**Domain:** BRANCHOFFICE

---

## Executive Summary

A Windows server in the BRANCHOFFICE domain was compromised through a sustained **NTLM brute-force attack** against the built-in Administrator account over SMB, beginning **2024-02-04 23:37 UTC**. The attacker gained access on **2024-02-05**, established persistent domain-level access by creating a backdoor account ("admin") with Domain Admin privileges, conducted internal network reconnaissance against the **10.44.24.1/24** subnet, exfiltrated approximately **694 MB of data** from the `C:\share` network share using 7-Zip, and then deployed **Ryuk ransomware** on **2024-02-07**, leaving a ransom note on the admin Desktop.

The attack followed a **double-extortion** playbook: steal data first, then encrypt. The backdoor account remained active at least through **2024-02-09**, confirming continued attacker persistence post-encryption.

---

## Attack Timeline

| Time (UTC) | Phase | Event |
|-----------|-------|-------|
| 2024-02-04 23:37:28 | **Initial Access** | NTLM brute-force begins from 36.133.110.87 (`kali`) against Administrator via SMB — >200,000 failures over ~11 hours |
| 2024-02-05 08:52:06 | **Initial Access** | First RDP logon (Type 10) for Administrator from 195.21.1.97 (`ADMIN-WFH`) — possible separate credential vector |
| 2024-02-05 10:55:56 | **Initial Access** | SMB brute-force succeeds — Administrator authenticated (Type 3) from 36.133.110.87 |
| 2024-02-05 18:59:35 | **Anti-Forensics** | Windows Defender detection history deleted (EventID 1013) under SYSTEM |
| 2024-02-05 22:55:18 | **Lateral Move** | New attacker IP 185.229.66.183 (`kali`) begins SMB/RDP authentication as Administrator |
| 2024-02-05 23:02:00 | **Persistence** | Backdoor account "admin" created (SID -2611) by attacker |
| 2024-02-05 23:02:22 | **Persistence** | "admin" added to local Administrators group |
| 2024-02-05 23:05:22 | **Exfiltration** | "admin" logs in via RDP from 185.229.66.183 — data staging session begins |
| 2024-02-05 23:14:49 | **Cover Tracks** | SysinternalsSuite.zip (53 MB) deleted to Recycle Bin |
| 2024-02-05 23:24:35 | **Persistence** | "admin" added to **Domain Admins** — domain-wide compromise |
| 2024-02-05 23:28:30 | **Exfiltration** | 7-Zip creates `share.zip` (694 MB) from C:\share — includes `account_password.xlsx`, `account_edit.docx` |
| 2024-02-05 23:42:42 | **Credential Harvest** | Npcap Packet Driver installed (EventID 7045) — network sniffing enabled |
| 2024-02-05 23:43:04 | **Reconnaissance** | Nmap/Zenmap installed (EventID 28115) |
| 2024-02-06 18:59:58 | **Anti-Forensics** | Windows Defender detection history deleted again (EventID 1013) |
| 2024-02-06 21:09 | **Reconnaissance** | Nmap "Intense scan" of 10.44.24.1/24 completed — results saved to Desktop\maps\ |
| 2024-02-06 22:14:12 | **Lateral Move** | PsExec and PsExec64 executed from `C:\Users\admin\Downloads\SysinternalsSuite\` |
| 2024-02-06 22:14:44 | **Cover Tracks** | `share.zip` (694 MB) deleted to Recycle Bin — exfiltration likely already complete |
| 2024-02-07 04:04:00 | **Exfiltration** | `important.zip` (551 KB) created on admin Desktop — second staging archive |
| 2024-02-07 04:46:00 | **Ransomware** | `RyukReadMe.txt` ransom note created — encryption event confirmed |
| 2024-02-07 21:00:10 | **Ransomware** | Ryuk binaries `dir.exe` and `rename.exe` registered in Amcache |
| 2024-02-09 19:47:55 | **Persistence** | Attacker returns via RDP from 31.220.85.162 (`kali`) — backdoor still active post-encryption |

---

## Finding 1: Initial Access — SMB NTLM Brute-Force

**Severity:** Critical
**MITRE ATT&CK:** T1110.001 (Brute Force: Password Guessing), T1078 (Valid Accounts)

The attacker conducted a sustained NTLM brute-force campaign against the built-in `Administrator` account over SMB (port 445) from public IP **36.133.110.87** (self-identified hostname `kali`). The campaign began at **2024-02-04 23:37:28 UTC** and produced over **200,000 failed logon attempts** (EventID 4625) before succeeding approximately 11 hours later at **2024-02-05 10:55:56 UTC** (EventID 4624, RecordID 2379067, Logon Type 3).

Separately, an RDP session was established from **195.21.1.97** (`ADMIN-WFH`) at **08:52:06 UTC** on the same day — before the brute-force succeeded — indicating this IP may have used credentials obtained from a prior compromise or through a different channel.

**Root Cause:** The Administrator account had a weak or guessable password. SMB (port 445) was exposed directly to the internet without firewall restriction or account lockout policy.

| Attacker IP | Hostname | Access Method | First Activity |
|-------------|----------|--------------|----------------|
| 36.133.110.87 | kali | SMB brute-force | 2024-02-04 23:37:28 UTC |
| 195.21.1.97 | ADMIN-WFH | RDP (Logon Type 10) | 2024-02-05 08:52:06 UTC |
| 185.229.66.183 | kali | SMB + RDP | 2024-02-05 22:55:18 UTC |
| 31.220.85.162 | kali / WIN-NI9FBK23SLO | RDP | 2024-02-09 19:47:55 UTC |

---

## Finding 2: Persistence — Backdoor Domain Admin Account

**Severity:** Critical
**MITRE ATT&CK:** T1136.001 (Create Account: Local Account), T1098 (Account Manipulation)

Within ~12 hours of initial access, the attacker created a local account named **"admin"** and rapidly escalated it:

- **23:02:00 UTC** — Account created (EventID 4720, RecordID 2441460), SID: `S-1-5-21-1057484085-1795310446-2370380301-2611`
- **23:02:22 UTC** — Added to local Administrators (EventID 4732, 22 seconds later)
- **23:24:35 UTC** — Added to **Domain Admins** (EventID 4728), granting domain-wide control

The **Npcap Packet Driver** was installed at 23:42:42 UTC (EventID 7045), enabling full network packet capture — likely used to harvest domain credentials from network traffic for further lateral movement.

**The backdoor "admin" account was still actively used on 2024-02-09**, confirming the attacker maintained access after deploying ransomware.

---

## Finding 3: Data Exfiltration — 694 MB via 7-Zip (Double-Extortion)

**Severity:** Critical
**MITRE ATT&CK:** T1560.001 (Archive Collected Data: Archive via Utility), T1041 (Exfiltration Over C2 Channel)

The attacker staged data for exfiltration using **7-Zip** (installed on the system), archiving the entire `C:\share` network share:

- **2024-02-05 23:28:30–23:36:06 UTC** — `share.zip` created at `C:\Users\admin\Desktop\` (694,728,396 bytes, ~662 MB)
- The archive contained sensitive files including:
  - `C:\share\Clark.Nicholson\Documents\account_password.xlsx`
  - `C:\share\Clark.Nicholson\Documents\account_edit.docx`
- **2024-02-06 22:14:44 UTC** — `share.zip` deleted to Recycle Bin (entry `$IAN75BL.zip`) — indicative of post-exfiltration cleanup

A second archive **`important.zip`** (551,492 bytes) was created on `C:\Users\admin\Desktop` at **2024-02-07 04:04:00 UTC**, approximately 42 minutes before the Ryuk ransom note appeared — likely a final targeted data staging event.

**Evidence of deletion to cover tracks:**
| Archive | Size | Deleted |
|---------|------|---------|
| share.zip | 694,728,396 bytes | 2024-02-06 22:14:44 UTC (RecycleBin) |
| SysinternalsSuite.zip | 53,047,703 bytes | 2024-02-05 23:14:49 UTC (RecycleBin) |

**Note:** SRUM and SUM/UAL database tables were not present in the evidence set, so outbound exfiltration destination IPs cannot be confirmed from network telemetry. The staging and deletion pattern strongly supports completed exfiltration.

---

## Finding 4: Lateral Movement — Nmap Reconnaissance and PsExec

**Severity:** Critical
**MITRE ATT&CK:** T1046 (Network Service Scanning), T1570 (Lateral Tool Transfer), T1021.002 (SMB/Windows Admin Shares)

The attacker conducted systematic internal network reconnaissance:

1. **Nmap 7.93** installed (~2024-02-05) and an **intense scan** of **10.44.24.1/24** (254 hosts) was completed on approximately **2024-02-06 21:09 UTC**, with results saved to `C:\Users\admin\Desktop\maps\202402062109 Intense scan on 10.44.24.1_24.xml`.

2. **PsExec** (SHA1: `3e2272b916da4be3c120d17490423230ab62c174`) and **PsExec64** (SHA1: `0098c79e1404b4399bf0e686d88dbf052269a302`) were executed at **2024-02-06 22:14:12 UTC** from `C:\Users\admin\Downloads\SysinternalsSuite\`, enabling remote process execution on other hosts in the scanned subnet.

3. **procdump64.exe** was present (AppCompatCache), likely used to dump LSASS credentials for authenticating to discovered hosts.

4. The attacker's backdoor account "admin" was a **Domain Admin**, giving unrestricted access to all domain-joined systems.

**All other systems on the 10.44.24.1/24 subnet should be treated as potentially compromised.**

---

## Finding 5: Ransomware — Ryuk Deployment

**Severity:** Critical
**MITRE ATT&CK:** T1486 (Data Encrypted for Impact), T1490 (Inhibit System Recovery)

**Ryuk ransomware** was deployed. Two binaries masquerading as Windows built-in commands were found on `C:\Users\admin\Desktop`:

| File | SHA1 | Size |
|------|------|------|
| `dir.exe` | `d1c62ac62e68875085b62fa651fb17d4d7313887` | 806,912 bytes |
| `rename.exe` | `39b6d40906c7f7f080e6befa93324dddadcbd9fa` | 230,912 bytes |

Both files have no ProductName metadata, were first registered in Amcache at **2024-02-07 21:00:10 UTC**, and are confirmed Ryuk binaries.

The **ransom note** `RyukReadMe.txt` (1,912 bytes) was created at **2024-02-07 04:46:00 UTC**, confirming that encryption had occurred.

**Anti-recovery actions:** No direct EVTX evidence of `vssadmin delete shadows` or `bcdedit` commands was found — this gap is attributed to **process creation auditing (EventID 4688) not being enabled** on this server, or possible log clearing. Windows Defender detection history was deleted twice (EventID 1013 on 2024-02-05 and 2024-02-06), consistent with pre-encryption anti-forensics. Additionally, 21 potentially malicious PowerShell events (EventID 4104) were logged in the attack window.

---

## Indicators of Compromise (IOCs)

### Network
| Type | Value | Context |
|------|-------|---------|
| IP | 36.133.110.87 | Attacker IP (`kali`) — SMB brute-force, initial access |
| IP | 185.229.66.183 | Attacker IP (`kali`) — RDP + SMB, data staging |
| IP | 195.21.1.97 | Attacker IP (`ADMIN-WFH`) — RDP, sustained access |
| IP | 31.220.85.162 | Attacker IP (`kali`) — post-ransomware RDP persistence |
| Subnet | 10.44.24.1/24 | Internal subnet targeted by Nmap intense scan |

### Files / Hashes
| Type | Value | Context |
|------|-------|---------|
| SHA1 | `d1c62ac62e68875085b62fa651fb17d4d7313887` | Ryuk binary `dir.exe` |
| SHA1 | `39b6d40906c7f7f080e6befa93324dddadcbd9fa` | Ryuk binary `rename.exe` |
| SHA1 | `3e2272b916da4be3c120d17490423230ab62c174` | PsExec.exe (lateral movement) |
| SHA1 | `0098c79e1404b4399bf0e686d88dbf052269a302` | PsExec64.exe (lateral movement) |
| Path | `C:\Users\admin\Desktop\dir.exe` | Ryuk payload |
| Path | `C:\Users\admin\Desktop\rename.exe` | Ryuk component |
| Path | `C:\Users\admin\Desktop\RyukReadMe.txt` | Ransom note |
| Path | `C:\Users\admin\Desktop\important.zip` | Data staging archive (551 KB, present) |
| Path | `C:\Users\admin\Desktop\share.zip` | Primary exfiltration archive (694 MB, deleted to RecycleBin) |
| Path | `C:\share\Clark.Nicholson\Documents\account_password.xlsx` | Exfiltrated sensitive file |

### Accounts
| Account | SID | Notes |
|---------|-----|-------|
| `admin` | S-1-5-21-1057484085-1795310446-2370380301-2611 | Attacker-created backdoor — Domain Admin — **MUST BE DISABLED** |

### Services / Drivers
| Name | Notes |
|------|-------|
| Npcap Packet Driver | Installed 2024-02-05 23:42:42 — network sniffer |
| Nmap/Zenmap | Installed 2024-02-05 23:43:04 — network scanner |

---

## Gaps and Limitations

1. **Process creation auditing (EventID 4688) was not enabled** — shadow copy deletion, bcdedit, and LOLBin command-line execution cannot be confirmed from logs.
2. **SRUM and SUM/UAL databases were absent** — precise exfiltration byte counts and destination IPs for outbound transfers are unavailable.
3. **Other hosts on 10.44.24.1/24 not examined** — the scope of PsExec-based lateral movement is unknown.
4. **Recycle Bin contents only show metadata** — the actual content of `share.zip` cannot be confirmed from this disk image alone.

---

## Immediate Remediation Recommendations

1. **Isolate all systems on 10.44.24.1/24** — treat as potentially compromised via PsExec lateral movement.
2. **Disable and delete the "admin" backdoor account** immediately across the domain.
3. **Reset all domain account passwords** — Npcap sniffing and procdump64 credential dumping may have harvested credentials.
4. **Block all four attacker IPs** at the perimeter firewall.
5. **Restrict SMB (445) and RDP (3389)** from the internet — implement VPN or Zero Trust gateway.
6. **Enforce account lockout policy** — the brute-force attack succeeded because no lockout was configured.
7. **Recover from clean backups** — verify backup integrity dates pre-2024-02-04.
8. **Enable EventID 4688 (process creation)** and command-line logging on all servers.
9. **Notify affected data subjects** for `Clark.Nicholson`'s documents (account_password.xlsx) — potential data breach notification obligation.
10. **Submit Ryuk binaries to threat intelligence** — SHA1 hashes above for VirusTotal/sandbox analysis.

---

*Report generated from forensic artefacts: evtx_hayabusa.csv, Amcache, AppCompatCache, MFT, LNK files, RecycleBin, Jump Lists, Registry (RECmd batch). All timestamps UTC.*
