# x=int(input("Mời bạn nhập số nguyên " ))
# if x%2 ==1:
    # print("số bạn vừa nhập là số lẻ")
# else: 
    # print("số bạn vừa nhập là số chẵn")
# x=float(input("Mời bạn nhập một số nguyên "))
# if x>0:
    # print("số bạn nhập là số dương")
# elif x==0:
    # print("số bạn nhập là số 0")
# else:
    # print("số bạn nhập là số âm")
# print("Sau đây tôi sẽ giúp bạn giải phương trình bậc nhât có dạng ax+b=0")
# a=float(input("mời bạn nhập số a "))
# b=float(input("mời bạn nhập số b "))
# if a==0:
    # print("phương trình vô nghiệm")
# else:
    # print("sau đây là nghiệm của phương trình ", -b/a)
from math import sqrt
print("Đây là chương trình giải phương trình bậc 2 có dạng ax^2 + bx + c=0")
a=float(input("Xin mời bạn nhập a "))
b=float(input("Xin mời bạn nhập b "))
c=float(input("Xin mời bạn nhập c "))
if a==0:
    if b==0:
        if c==0:
            print("Phương trình có vô số nghiệm")
        else:
            print("Phương trình vô nghiệm")
    else:
        print("Phương trình có nghiệm là: ", -c/b)
else:
    delta = b**2-4*a*c
    if delta <0:
        print("Phương trình vô nghiệm")
    elif delta == 0:
        print("Phương trình có nghiệm kép là ", -b/(2*a))
    else:
        x1=(-b-sqrt(delta))/(2*a)
        x2=(-b+sqrt(delta))/(2*a)
        print(f"Phương trình có 2 nghiệm là x1= {x1} và x2= {x2}")
