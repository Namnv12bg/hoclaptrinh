# lst= (2,3,5,7,9)
# print(type(lst))
# for value in lst:
#     print(value)
# #Vậy hàm range được hiểu như sau:
# print(type(range(100)))
# lst_range=list(range(100))
# for i in lst_range:
#     print(i, end=" ")
# set= {2,3,5,7,9}
# print("\n", type(set))
# for value1 in set:
#     print(value1)
# d={
#     "a":1,
#     "b":2,
#     "c":3,
#    }
# print( type(d))
# for key in d:
#     print(d)
# for key in d:
#     print(key)
# print(d.values())
# print(type(d.values()))
# for vlue in d.values():
#     print(vlue)
# for item in d.items():
#     print(item)
#     key,value = item
#     print(key)
#     print(value)
#     print("-"*30)
#List comprehention
# lst=[1,2,3,4]
# #new_list =[2,4,6,8]
# # new_lst =[]
# # for vlue in lst:
# #     vlue_double = vlue*2
# #     new_lst.append(vlue_double)
# # print(new_lst)
# new_lst = [val*2 for val in lst]
# print(new_lst)


#Set prehention
# set={"a","b", "c"}
# new_set = {vlue.upper() for vlue in set}
# print(new_set)
#Dict prehention
# d={
#     "a":1,
#     "b":2,
#     "c":3
# }
# newd={
#     k:v*2
#     for k,v in d.items()
# }
# print(newd)
# print(d.items())
# print(type(d.items()))
# numbers= [100,344,256,211,-46,37]
# # tong =0
# # for x in numbers:
# #     if x%2 != 0:
# #         tong=tong + float(x)
# # print(tong)
# # newnumber = [v for v in numbers if v%2!=0]
# # print(newnumber)
# # total=sum(newnumber)
# # print(total)
# newnumber = [2*v if v%2==0 else v*3 for v in numbers]
# print(newnumber)
# print(sum(newnumber))
# newnumber1 =[]
# for i in numbers:
#     if i%2==0:
#         newnumber1.append(2*i)
#     else:
#         newnumber1.append(3*i)
# print(newnumber1)
#enumerate
lst=[1,2,3,4,5]
# print(set(enumerate(lst,start=1)))
for x,y in enumerate(lst):
    if x% 2!=0:
        print (x, " ", y)