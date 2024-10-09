friends=["Jen", "Jack" ,"Kenne", "Jelly","Bob", "Henry", "Anne" ]
string1="xinchaocacban"
a=slice(4)
print(friends[0:4])
print(string1[0:4])
print(friends[-4:])
print(friends[::-1])
print(friends[1:])
new_string=friends[:]
new_string2=friends.copy()
print(new_string)
print(new_string2)
print(friends[1:-1])
student=[["SV001","Bob",23],["SV002", "Kenny",34], ["SV003", "Henry", 45]]
print(f"Thông tin của sinh viên thứ nhất là ID = {student[0][0]} Name= {student[0][1]} Age = {student[0][2]}")
print(student[1][2])
print(student[1:])
print(student[2][0])