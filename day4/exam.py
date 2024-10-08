ten_ban = ["Hùng", "Lệ", "Sơn", "Hà"]
print(ten_ban[0])
ten_ban[0]="Hằng"
print(ten_ban)
print(len(ten_ban))
print(ten_ban.count("Hằng"))
ten_ban.insert(1,"Thắng")
print(ten_ban)
last=ten_ban.pop()
print(last)
print(ten_ban)
#xóa 1 giá trị pop, remove
#ten_ban.remove("Thắng")
#print(ten_ban)
#so2=ten_ban.pop(1)
#print(ten_ban)
del ten_ban[1]
print(ten_ban)
ten_ban.extend[""]