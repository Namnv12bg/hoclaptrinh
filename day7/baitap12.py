art_student={"John","Max", "Anna", "Bob", "Obito"}
math_student={"Max", "Merry", "David", "Anna", "Naruto", "John"}
both=math_student&art_student
print(both)
print(art_student.intersection(math_student))
art_not_math=art_student-math_student
print(art_not_math)
print(art_student.difference(math_student))
print(math_student.difference(art_student))
