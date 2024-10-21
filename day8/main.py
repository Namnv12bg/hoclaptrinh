#if else, elif
# n=int(input("mời bạn nhập số "))
""" if n>0:
    print("So dương")
elif n==0:
    print("số 0")
else:
    print("số âm") """
# print("n chia hết cho 3" if n %3==0 else "n không chia hết cho 3")
# a=int(input("a= "))
# b=int(input("b= "))
# m =a
# # print(f"số lớn nhất là {a if a>b else b}")
# if b>a:
#     m=b
#     print(m)
# a,b=map(int,input().split())
# print(a if a>b else b)
# #cách chạy split sẽ chia các con số input nhập vào cách nahu mặc định bằng dấu cách thành cách list chuỗi, sau đó hàm int sẽ chuyển map từng ký tự trong chuôi
# # Hàm eval để đánh giá biểu thức bên trong chuỗi, ví dụ:
# print(eval("1*8+5*9"))
# lst=list(map(eval,input().split()))
# print(lst)
# lst=[1,2,3,4,5,6]
# print(*lst,sep=" và ")
# lst=[4,5,7,8,9,6,2]
# lst.sort()
# print(lst)
# new_lst = sorted(lst,reverse=True)
# print(new_lst)
# char ="b"
# charhoa="B"
# print("ASCII code ",ord(char)-ord(charhoa))
# ascii_code=65
# print(chr(ascii_code))
# lst=list(map(eval,input().split()))
# print(lst)
# print(divmod(4,5))
# a=int(input("mời bạn nhập số giây", ))
# tup1=divmod(a,360)
# tup2=divmod(tup1[1],60)
# print(f"Quy đổi ra được {tup1[0]} giờ, {tup2[0]} phút và {tup2[1]} giây")
# intnumber=17
# binary=bin(intnumber)
# print(binary)
# # print(binary[2:])
# # bin()
# print(format(intnumber,"b"))
# print(list(range(255)))
r1=range(255)
r2=range(100)
a=int(input("xin mời bạn nhập giá trị ",))
b=(a*255)//100
print("giá trị tương ứng trong mã 255 là",b)