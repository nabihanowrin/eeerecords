"""
The department's faculty members, and who teaches which 5th-semester course.

Source: the department booklet (Faculty Members pages), corrected by
Nabiha where it is out of date: the chairman is now Dr. Kazi Tanvir Ahmmed,
and teachers who are teaching this semester are not marked as on leave.
Edit this file when anything changes; the website reads it at start-up.
"""

CHAIRMAN = "Dr. Kazi Tanvir Ahmmed"

# (name, designation, email, on study leave)
FACULTY = [
    ("Dr. Kazi Tanvir Ahmmed",          "Associate Professor", "tanvir@cu.ac.bd",            False),
    ("Dr. Md. Fazlul Kader",            "Professor",           "fkader@cu.ac.bd",            False),
    ("Dr. Jamal Uddin Ahamed",          "Professor",           "ahamed.jamal@cu.ac.bd",      False),
    ("Dr. Hasan Khaled Rouf",           "Professor",           "hasan.rouf@cu.ac.bd",        False),
    ("Dr. Mohammad Abdul Alim",         "Professor",           "mohammadabdulalim@cu.ac.bd", False),
    ("Dr. Mohammad Arif Iftakher Mahmood", "Associate Professor", "arif.iftakher@gmail.com", False),
    ("Md. Murshadul Hoque",             "Associate Professor", "m.hoque@cu.ac.bd",           False),
    ("Dr. Md. Shah Alam",               "Associate Professor", "shah.alam@cu.ac.bd",         False),
    ("Mohammad Shuhrawardy",            "Associate Professor", "mswardy@cu.ac.bd",           False),
    ("Ariful Islam",                    "Assistant Professor", "ariful@cu.ac.bd",            False),
    ("S. M. Abu Zahed Chowdhury",       "Assistant Professor", "zahed_apece@cu.ac.bd",       False),
    ("Sabuj Chowdhury",                 "Assistant Professor", "sabuj.apece@cu.ac.bd",       False),
    ("Sabrina Alam",                    "Assistant Professor", "sabrina.apece@cu.ac.bd",     False),
    ("Md. Didarul Alam",                "Assistant Professor", "didar.apece@cu.ac.bd",       True),
    ("Mohammad Shah Alamgir",           "Assistant Professor", "shah_a@cu.ac.bd",            True),
    ("Saumitra Kumar Kuri",             "Assistant Professor", "skkuri@cu.ac.bd",            False),
    ("Alamgir Hossain",                 "Assistant Professor", "ah.apece@cu.ac.bd",          True),
    ("Md. Shariful Islam",              "Assistant Professor", "shariful2488@cu.ac.bd",      False),
    ("Tauhidul Haque",                  "Assistant Professor", "tauhidulhaque@cu.ac.bd",     True),
    ("Sadia Sultana",                   "Assistant Professor", "sadia@cu.ac.bd",             False),
    ("Jewel Dey",                       "Lecturer",            "jewel@cu.ac.bd",             False),
    ("Tahasin Ahmed Fahim",             "Lecturer",            "tahasin@cu.ac.bd",           False),
    ("Mohammad Jahed",                  "Lecturer",            "jahed.eee@cu.ac.bd",         False),
    ("Sangita Rani Basu",               "Lecturer",            "sangita@cu.ac.bd",           False),
    ("Israt Jahan",                     "Lecturer",            "israt@cu.ac.bd",             False),
    ("Md. Ali Munna",                   "Lecturer",            "mdalimunna.eee@cu.ac.bd",    False),
]

# who teaches each 5th-semester course (2023–24 batch)
COURSE_TEACHERS = {
    "EEE 510": ["Md. Murshadul Hoque"],
    "EEE 511": ["Dr. Kazi Tanvir Ahmmed"],
    "EEE 512": ["Dr. Kazi Tanvir Ahmmed", "Ariful Islam"],
    "EEE 513": ["Sabrina Alam"],
    "EEE 514": ["Sabrina Alam"],
    "EEE 515": ["Mohammad Shuhrawardy"],
    "EEE 516": ["Sangita Rani Basu", "Mohammad Shuhrawardy"],
    "CSE 517": ["Sadia Sultana"],
    "CSE 518": ["Sadia Sultana", "Dr. Md. Fazlul Kader"],
    "EEE 519": ["Tahasin Ahmed Fahim"],
}

CONTACT = {
    "address": "Department of Electrical and Electronic Engineering, Faculty of Engineering, "
               "University of Chittagong, Chittagong-4331, Bangladesh",
    "email": "chairman.eee@cu.ac.bd",
    "website": "http://cu.ac.bd/eee",
    "phone": "88-031-2606001-10, 726311-14, 2606015-27 (ext. 4392)",
    "fax": "88-031-2606014, 2606145",
}


def listing():
    return [{"name": n, "designation": d, "email": e, "on_leave": leave, "chairman": n == CHAIRMAN}
            for n, d, e, leave in FACULTY]


def by_email(email):
    email = (email or "").strip().lower()
    for n, d, e, leave in FACULTY:
        if e.lower() == email:
            return n
    return None


def apply_course_teachers(connect):
    """Write the teacher names into the course list, so every page shows them."""
    con = connect()
    for code, names in COURSE_TEACHERS.items():
        con.execute("UPDATE course_meta SET teacher=? WHERE course_id IN "
                    "(SELECT course_id FROM courses WHERE code=? AND semester=5)",
                    (" / ".join(names), code))
    con.commit()
    con.close()
