import pathlib
p = pathlib.Path(r"E:\dev\TermPaws\dev\TermPaws\backend\app\api\routes\chat.py")
text = p.read_text(encoding="utf-8")
old = "                        stop_after_final_robot_delivery = delivery_is_final\n"
assert text.count(old) == 1
text = text.replace(old, "                        stop_after_final_robot_delivery = True\n")
p.write_text(text, encoding="utf-8")
print("delivery_is_final NameError fixed")
