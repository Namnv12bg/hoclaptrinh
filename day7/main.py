# set1={1,4,3,2}
# set2={2,3,8,7}
# set3=set1.intersection(set2) #có thể là list, tupble, dictionary, là set
# print(set3)
# print(set1 & set2) #bắt buộc set 1 và set2 phải là set
# set4=set2.difference(set1) #lấy phần tử có trong set 1 không có trong set 2
# print(set4)
# print(set2-set1) #phép trừ set sẽ xóa phần trùng 2 set và giữ lại phần khác biệt của sét bị trừ
# set5=set1.union(set2) #phép lấy ra các phần tử trong cả 2 set - gộp set
# print(set5)
# print(set1|set2) #gộp 2 set
# set6={10,2,45,16}
# set7=set1.union(set2).union(set6)
# print(set7)
# print(set1|set2|set6)
# #lấy các phần khác nhau trong cả 2 set
# set8=set1.symmetric_difference(set2)
# print(set8)
# print(set1^set2)
#dictionary hiện dạng key:value
import json
student={
    "name":"Bob",
    "age": 24,
    "grade":[23,45,35,53]
}
# print(student)
# print(json.dumps(student, indent=2))
# value=student.get("id","abc")
# print(value)
# student["id"]="SV001"
# student["name"]="Jack"
# print(student)
#udate nhiều giá trị
# student.update(id="SV0001",gender="Male")
# infor={"id":"SV001","gender":"male"} #dictionary
# student.update(infor)
#dùng chuỗi Tupble để add (chuỗi là ngoặc vuông, Tupble là ngaowcj tròn, cụ thể như sau)
# infor=[("id", "SV001"),("gender","Male")]
# student.update(infor)
# print(student)
# print(json.dumps(student, indent=3))

#xóa đi 1 key, cách 1 dung pop
# value=student.pop("name")
# print(value)
# Cách 2 dùng del
# del student["name"]
#lấy ra phần tử ở cuối 
# tup=student.popitem()
# print(tup)
# print(json.dumps(student, indent=3))
# Lấy các key
key=list(student)
print(key)
# lấy các value
value=list(student.values())
print(value)
# lấy list tupble
items=list(student.items())
print(items)
print(student)
print(type(items))