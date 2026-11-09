from diagnose_steps import the_box
from ltf_approach_engine import is_qualifying_htf_zone

print("the_box text:", the_box.get("text"))
print("is_qualifying_htf_zone:", is_qualifying_htf_zone(the_box))
print("the_box left:", the_box.get("left"))
print("the_box right:", the_box.get("right"))
print("the_box is_mitigated:", the_box.get("is_mitigated"))
print("the_box is_broken:", the_box.get("is_broken"))
print("the_box mitigated_time:", the_box.get("mitigated_time"))
