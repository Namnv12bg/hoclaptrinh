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
lst=[1,2,3,4,5,6]
print(*lst,sep=" và ")