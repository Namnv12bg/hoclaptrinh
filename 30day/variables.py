last_name="Kiet"
first_name="Pham"
name=" ".join([first_name,last_name])
country="Viet Nam"
city="Ha Noi"
age=15
year=2024
is_true=True
ten,tuoi,lop_hoc,gioi_tinh="nam",25,"A1234","male"
print(first_name)
print(last_name)
print(name)
print(country)
print(city)
print(ten,tuoi,lop_hoc,gioi_tinh)
print(" ".join([ten,str(tuoi),lop_hoc,gioi_tinh]))
new=[ten,tuoi,lop_hoc,gioi_tinh]
print(new)
print(type(new))
print(" ".join(list(map(str,new))))