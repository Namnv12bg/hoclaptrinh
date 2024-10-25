#đếm số lượng số nguyên tố trong đoạn 1-100
a=0
b=0
for i in range (2,101):
    for j in range (2,i):
        if i%j ==0:
            break 
    else:    
        a=a+1
print(a)