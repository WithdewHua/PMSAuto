import os
import re

src_path = "/GoogleDrive/Inbox/NSFW"
dst_path = "/GoogleDrive/NSFW"

src_dirs = os.listdir(src_path)
dst_dirs = os.listdir(dst_path)

for src_dir in src_dirs:
    if os.path.isdir(os.path.join(src_path, src_dir)) and (src_dir != "failed") and (not re.search(r"\w+-?\d{3}", src_dir)):
        if not os.listdir(os.path.join(src_path, src_dir)):
            print("Empty directory: " + src_dir)
            continue
        else:
            if src_dir in dst_dirs:
                print("Directory already exists: " + src_dir)
                for dir in os.listdir(os.path.join(src_path, src_dir)):
                    if os.path.exists(os.path.join(dst_path, src_dir, dir)):
                        print("Folder already exists: " + dir)
                        continue
                    else:
                        os.rename(os.path.join(src_path, src_dir, dir), os.path.join(dst_path, src_dir, dir))
                        print("Folder moved: " + dir)

                # os.system(f'mv {src_path}/{src_dir}/* {dst_path}/{src_dir}')
            else:
                print("Moving directory: " + src_dir)
                os.system(f'mv "{src_path}/{src_dir}" {dst_path}')
