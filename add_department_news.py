"""
Fills the landing page's achievement slider with real, recent news
(2024-2026 only), replacing the empty "Sample" cards one by one.

Source for each entry: the IEEE Student Branch, University of Chittagong
official Facebook page (facebook.com/IEEESBCU). Only what the post says.

Run once:   python add_department_news.py
Safe to run again: it rewrites its own entries, never duplicates them.
"""

import sqlite3

# Shown on the slider in this order, top to bottom.
# (sample card it replaces or None, year, title, detail, picture)
ENTRIES = [
    ("Sample — award or competition result", 2026,
     "Champions of VLSIthon 3.0",
     "Md Rakib Hasnat Akash and Md Shahariar Khan Emon (Team Deviation) won VLSIthon 3.0, "
     "hosted by Ulkasemi with UVTI and IEEE Student Branch, AIUB, ahead of 106 teams from "
     "across Bangladesh · IEEE Student Branch, CU",
     "photos/vlsithon3.png"),
    (None, 2026,
     'Seminar: "Integrated Photonics for Next-Generation Optical Communication and Sensing"',
     "Dr. Mohammad Shuhrawardy, Associate Professor, Dept. of EEE, University of Chittagong · "
     "16 July 2026, Department of EEE · IEEE Student Branch, CU with the IEEE Photonics Society "
     "Bangladesh Chapter",
     "photos/seminar-photonics.jpg"),
    ("Sample — workshop or seminar", 2026,
     'Seminar: "Autonomous Biomedical Machines"',
     "Multimodal biosensing, edge intelligence, adaptive control and engineering of medtech beyond "
     "the laboratory · Ahmed Sajidan Jarjis Rafsan, Founder, Apex Biomedical Innovation Lab · "
     "2 September 2026, Room 117, IT Building · Dept. of EEE Seminar Series #04 · "
     "IEEE Student Branch, CU, supported by the Optica Student Chapter, CU",
     "photos/seminar-biomedical.jpg"),
    ("Sample — alumni milestone", 2026,
     "Alumnus: Dr. Hafizul Islam Chowdhury",
     "B.Sc. (2017) and M.Sc. (2019) from the University of Chittagong; Ph.D. (2024) and "
     "postdoctoral fellowship at the University of Central Florida; now Assistant Professor, "
     "Electrical & Computer Engineering, UNC Charlotte · computer architecture, secure "
     "processors, AI/ML and hardware security",
     "photos/alumni-hafizul.jpg"),
]

# empty sample cards to take off the slider
REMOVE = ("Sample — research paper accepted", "Sample — new laboratory equipment")

SOURCE = "office:ieee-sb-cu-facebook"

con = sqlite3.connect("records.db")
added = 0
# take our own entries off and put them back in reverse, so the newest id
# (shown first on the slider) is the first entry in the list above
con.execute("DELETE FROM achievements WHERE added_by=?", (SOURCE,))
for sample, year, title, detail, image in reversed(ENTRIES):
    if sample:
        con.execute("DELETE FROM achievements WHERE title=?", (sample,))
    con.execute("INSERT INTO achievements (title, detail, year, image, added_by) VALUES (?,?,?,?,?)",
                (title, detail, year, image, SOURCE))
    added += 1
con.execute(f"DELETE FROM achievements WHERE title IN ({','.join('?' * len(REMOVE))})", REMOVE)
con.commit()
con.close()
print(f"{added} entries on the slider.")
