friends = [("Bob", "Male"), ("Anna","Female"), ("Max","Male")]
chieudai=len(friends)
print("chiều dài list là ", chieudai)
phantudau=friends[0]
phantugiua=friends[1]
phantucuoi=friends[-1]
print(f"Bạn thứ nhất là: {phantudau} bạn ở giữa là {phantugiua} bạn ở cuối là {phantucuoi}")
print("kiểu của phần tử đầu là: ", type(phantudau))
print("kiểu của phần tử giữa là: ", type(phantugiua))
print("kiểu của phần tử cuối là: ", type(phantucuoi))
#set thì mở ngoặc nhọn, tubble thì mở ngoặc tròn, list thì mở ngoặc vuông, vì vậy khi gọi chúng ra ta dùng ngoặc tương ứng, chú ý không gọi được phần tử trong set
tenbanthu4 = input("Nhập tên bạn thứ 4 ")
gioitinhbanthu4=input("nhập giới tính bạn thứ 4 ")
thongtinbanthu4 = (tenbanthu4, gioitinhbanthu4)
friends.append(thongtinbanthu4)
print(friends)