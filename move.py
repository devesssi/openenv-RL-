import os
import shutil

src = r"e:\programs2\openenv(RL)\devops_sandbox"
dst = r"e:\programs2\openenv(RL)"

for item in os.listdir(src):
    s = os.path.join(src, item)
    d = os.path.join(dst, item)
    if os.path.exists(d):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        else:
            os.remove(d)
    shutil.move(s, d)

print("Moved successfully")
