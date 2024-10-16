artstudent = {"John", "Max", "Anna", "Bob", "Obito"}
mathstudent={'Max', 'Merry', 'David', 'Anna', 'Naruto', 'John'}
# Hàm lấy giao nhau 2 chuỗi là intersection (giao nhau)/ dấu và
intersec=artstudent&mathstudent
intersec1=artstudent.intersection(mathstudent)
print(intersec)
print(intersec1)
#Tìm bạn học vè nhưng không học toán, hàm different
vekhongtoan=artstudent.difference(mathstudent)
print(artstudent-mathstudent)
print(vekhongtoan)
# Tìm những người học toán nhưng không học vẽ
toankhongve=mathstudent.difference(artstudent)
print(toankhongve)
print(mathstudent-artstudent)
#Tìm những người học vẽ hay toán 
print(artstudent^mathstudent)
hoc1trong2 = mathstudent.symmetric_difference(artstudent)
print(hoc1trong2)
#tìm tất cả những người bạn
tatcahocsinh=artstudent.union(mathstudent)
print(tatcahocsinh)
print(mathstudent|artstudent)
#Bài tập 2
album_info= {
    "albumname":"The Dark side  ",
    "band": "pink",
    "realease Year":1973,
    "tracklist": [
        "Speak to me",
        "Beathe",
        "on the run",
        "time",
        "monney"
    ]

}
print(album_info["albumname"])
print(album_info.get("albumname"))
print(album_info["realease Year"])
print(album_info.get("realease Year"))
# new=album_info.pop("tracklist")
# print(new)
del album_info["tracklist"]
print(album_info)
# album_info["amont"]=2000
album_info.update(amont=2000)
print(album_info)
#map map(ham,[cac gia tri cua list]) => map se trả về 1 list mới qua tác vụ của hàm
#ví dụ
print(map(str,[1,2,3,5,6]))