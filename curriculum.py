"""
Data only — no logic.

COURSES: every course in the B.Sc. Engg. (EEE) curriculum, sessions
2022-23 and 2023-24, read from the department's curriculum booklet.
Each row: (semester, code, title, credits, kind, lab it pairs with)
credits None = the photo was unclear, check the booklet.

CLASS_2023_24: the 2023-24 session, names and rolls from the EEE 413
sheet. Names and rolls only — no marks.
"""

COURSES = [
    # ---------------- 1st semester ----------------
    (1, "EEE 111", "Electrical Circuit I", 3, "theory", "EEE 112"),
    (1, "EEE 112", "Laboratory on Electrical Circuit I", 2, "lab", None),
    (1, "CSE 113", "Computer Programming and Numerical Analysis", 3, "theory", "CSE 114"),
    (1, "CSE 114", "Laboratory on Computer Programming and Numerical Analysis", 1, "lab", None),
    (1, "ENG 151", "Technical English", 3, "theory", None),
    (1, "MATH 161", "Calculus, Vector and Tensor Analysis", 3, "theory", None),
    (1, "PHY 171", "Acoustics and Optics", 3, "theory", "PHY 172"),
    (1, "PHY 172", "Laboratory on Acoustics and Optics", 1, "lab", None),
    (1, "EEE 110", "Engineering Drawing", 1, "lab", None),

    # ---------------- 2nd semester ----------------
    (2, "EEE 211", "Electrical Circuit II", 3, "theory", "EEE 212"),
    (2, "EEE 212", "Laboratory on Electrical Circuit II", 1, "lab", None),
    (2, "EEE 213", "Electronics I", 3, "theory", "EEE 214"),
    (2, "EEE 214", "Laboratory on Electronics I", 2, "lab", None),
    (2, "ECON 253", "Economics", 2, "theory", None),
    (2, "MATH 261", "Differential Equations and Matrices", 3, "theory", None),
    (2, "PHY 271", "Engineering Physics", 3, "theory", None),
    (2, "CHEM 281", "Physical and Inorganic Chemistry", 3, "theory", None),

    # ---------------- 3rd semester — credits unclear in the photo ----------------
    (3, "EEE 311", "Electronics II", None, "theory", "EEE 312"),
    (3, "EEE 312", "Laboratory on Electronics II", None, "lab", None),
    (3, "EEE 313", "Signals and Systems", None, "theory", "EEE 314"),
    (3, "EEE 314", "Laboratory on Signals and Systems", None, "lab", None),
    (3, "EEE 315", "Electrical Machine I", None, "theory", "EEE 316"),
    (3, "EEE 316", "Laboratory on Electrical Machine I", None, "lab", None),
    (3, "ACCO 351", "Industrial Management and Accounting", None, "theory", None),
    (3, "MATH 361", "Complex Variables, Integral Transforms, and Linear Algebra", None, "theory", None),
    (3, "EEE 310", "Workshop Practical", None, "lab", None),

    # ---------------- 4th semester ----------------
    (4, "EEE 411", "Solid State Electronics", 3, "theory", None),
    (4, "EEE 413", "Electrical Machine II", 3, "theory", "EEE 414"),
    (4, "EEE 414", "Laboratory on Electrical Machine II", 1, "lab", None),
    (4, "EEE 415", "Fundamental of Mechanical Engineering", 3, "theory", "EEE 416"),
    (4, "EEE 416", "Laboratory on Fundamental of Mechanical Engineering", 1, "lab", None),
    (4, "EEE 417", "Control System", 3, "theory", "EEE 418"),
    (4, "EEE 418", "Laboratory on Control System", 1, "lab", None),
    (4, "LAW 451", "Professional Law and Ethics", 2, "theory", None),
    (4, "STAT 471", "Statistics and Probability", 3, "theory", None),

    # ---------------- 5th semester ----------------
    (5, "EEE 511", "Digital Electronics", 3, "theory", "EEE 512"),
    (5, "EEE 512", "Laboratory on Digital Electronics", 1, "lab", None),
    (5, "EEE 513", "Communication Systems", 3, "theory", "EEE 514"),
    (5, "EEE 514", "Laboratory on Communication Systems", 1, "lab", None),
    (5, "EEE 515", "Engineering Electromagnetics", 3, "theory", "EEE 516"),
    (5, "EEE 516", "Laboratory on Engineering Electromagnetics", 1, "lab", None),
    (5, "CSE 517", "Computer Networks and Modern Computing", 3, "theory", "CSE 518"),
    (5, "CSE 518", "Laboratory on Computer Networks and Modern Computing", 1, "lab", None),
    (5, "EEE 519", "Power Transmission and Distribution", 3, "theory", None),
    (5, "EEE 510", "Electrical Services Design", 1, "lab", None),

    # ---------------- 6th semester ----------------
    (6, "EEE 611", "Measurements & Instrumentation", 3, "theory", "EEE 612"),
    (6, "EEE 612", "Laboratory on Measurements & Instrumentation", 1, "lab", None),
    (6, "EEE 613", "Microprocessor and Interfacing", 3, "theory", "EEE 614"),
    (6, "EEE 614", "Laboratory on Microprocessor and Interfacing", 1, "lab", None),
    (6, "EEE 615", "Digital Communication", 3, "theory", "EEE 616"),
    (6, "EEE 616", "Laboratory on Digital Communication", 1, "lab", None),
    (6, "EEE 617", "Power Systems Analysis", 3, "theory", "EEE 618"),
    (6, "EEE 618", "Laboratory on Power Systems Analysis", 1, "lab", None),
    (6, "EEE 619", "Microwave Engineering", 3, "theory", "EEE 620"),
    (6, "EEE 620", "Laboratory on Microwave Engineering", 1, "lab", None),

    # ---------------- 7th semester ----------------
    (7, "EEE 711", "Digital Signal Processing", 3, "theory", "EEE 712"),
    (7, "EEE 712", "Laboratory on Digital Signal Processing", 1, "lab", None),
    (7, "EEE 713", "Switchgear & Protection", 3, "theory", "EEE 714"),
    (7, "EEE 714", "Laboratory on Switchgear & Protection", 1, "lab", None),
    (7, "EEE 715", "Power and Industrial Electronics", 3, "theory", "EEE 716"),
    (7, "EEE 716", "Laboratory on Power and Industrial Electronics", 1, "lab", None),
    (7, "EEE 717", "Elective offered by the department", 3, "theory", None),
    (7, "EEE 719", "Elective offered by the department", 3, "theory", None),
    (7, "EEE 700", "Project / Thesis", 1, "lab", None),
    (7, "EEE 710", "Field Work / Industrial Training", 1, "lab", None),

    # ---------------- 8th semester ----------------
    (8, "EEE 811", "Material Engineering", 3, "theory", None),
    (8, "EEE 813", "VLSI Design", 3, "theory", "EEE 814"),
    (8, "EEE 814", "Laboratory on VLSI Design", 1, "lab", None),
    (8, "EEE 815", "Power Plant Engineering", 3, "theory", None),
    (8, "EEE 817", "Elective offered by the department", 3, "theory", None),
    (8, "EEE 819", "Elective offered by the department", 3, "theory", None),
    (8, "EEE 800", "Project / Thesis", 4, "lab", None),
]

# the 2023-24 session, from the EEE 413 Ranking sheet
CLASS_2023_24 = [
    ("22702015", "Motaher Hossen Sany"),
    ("23702006", "Ankita Das Shreya"),
    ("23702010", "Md. Nayem Uddin Nayan"),
    ("23702017", "Nie Nie Marma"),
    ("23702024", "Humayara Yeasmine"),
    ("23702040", "Tamanna Akter"),
    ("23702045", "Ayesha Nusrat"),
    ("23702049", "Maruf Hossain"),
    ("23702051", "Nabiha Nowrin"),
    ("23702053", "Joydip Talukder Tirtha"),
    ("23702055", "Sadia Sifat Rifa"),
    ("24702001", "Ayesha Akter"),
    ("24702002", "Lipy Barua"),
    ("24702004", "Mosroor Shakib Ahanaf"),
    ("24702005", "Sunjida Yeasmin Usha"),
    ("24702006", "Umme Azmira Liza"),
    ("24702007", "Md. Hossain Al-Mehedi Evon"),
    ("24702008", "Khalid Saifullah"),
    ("24702009", "Insha An Nahar"),
    ("24702010", "Habiba Sultana"),
    ("24702012", "Imdadul Haque Milon"),
    ("24702014", "A.F.M. Faik Adnan"),
    ("24702016", "Md. Shahajahan Alam Saimon"),
    ("24702017", "Md. Fahim Hasan Majumder"),
    ("24702020", "Md. Rifatul Islam"),
    ("24702021", "Abdullah Al Jawad"),
    ("24702023", "Nabil Numan"),
    ("24702024", "Mahbubur Rahman Khadem"),
    ("24702025", "Sonjoy Chakma"),
    ("24702026", "Md. Maharam Ali"),
    ("24702027", "Md. Rubayet Omar"),
    ("24702028", "Prattasha Majumder"),
    ("24702029", "Tanzila Sultana Saimu"),
    ("24702030", "Tanvirul Islam"),
    ("24702031", "Afrin Mostafa Riya"),
    ("24702033", "Md. Arafat Afran Riad"),
    ("24702034", "Md. Mahruf"),
    ("24702035", "Safia Salim"),
    ("24702036", "Md. Delowar Hoshen"),
    ("24702037", "Md. Isratul Evan Munna"),
    ("24702039", "Md. Mahmuddon Nobi Mahe"),
    ("24702040", "Minhaz Uddin Samrat"),
    ("24702041", "Md. Ahad Ali Sarker"),
    ("24702043", "Kazi Arshad Ahmed Ratul"),
    ("24702044", "Sharif Hasan"),
    ("24702045", "Sabrin Sultana"),
    ("24702046", "Jakia Sultana"),
    ("24702048", "Ummay Salma"),
    ("24702049", "Koushik Biswas"),
    ("24702050", "Syeda Muntaha Najah"),
    ("24702051", "Shahed Hossain"),
    ("24702053", "Raiyan Al Hassan"),
    ("24702054", "Suaid Ibn Humayun Nasif"),
    ("24702055", "Udoy Debnath"),
]

# the grading table, curriculum section on the grading system
# (lowest percentage for the grade, letter, grade point)
GRADES = [(80, "A+", 4.00), (75, "A", 3.75), (70, "A-", 3.50), (65, "B+", 3.25),
          (60, "B", 3.00), (55, "B-", 2.75), (50, "C+", 2.50), (45, "C", 2.25),
          (40, "D", 2.00), (0, "F", 0.00)]

PROMOTION_GPA = 2.00        # "a GPA of 2.00 or higher shall be promoted"
