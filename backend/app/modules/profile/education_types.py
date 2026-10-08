"""学历层次和学习形式的显式取值；不从旧文本自动回填用户事实。"""

from typing import Literal

DegreeLevel = Literal["HIGH_SCHOOL", "ASSOCIATE", "BACHELOR", "MASTER", "DOCTOR", "OTHER"]
StudyMode = Literal["FULL_TIME", "PART_TIME", "OTHER"]
