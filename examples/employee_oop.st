(* Employee polymorphism inspired by:
   https://stefanhenneken.net/2020/12/13/iec-61131-3-abstract-fb-vs-interface/

   STC models the example with IEC Edition 3 CLASS declarations. Properties,
   REFERENCE TO and TwinCAT abstract FUNCTION_BLOCK extensions are deliberately
   replaced by fields, interfaces and methods supported by the compiler. *)

INTERFACE IEmployee
METHOD GetMonthlySalary : LREAL
END_METHOD
END_INTERFACE

CLASS ABSTRACT EmployeeBase IMPLEMENTS IEmployee
VAR
    EmployeeNumber : UINT;
END_VAR

METHOD PUBLIC ABSTRACT GetMonthlySalary : LREAL
END_METHOD

METHOD PUBLIC GetEmployeeNumber : UINT
    GetEmployeeNumber := EmployeeNumber;
END_METHOD
END_CLASS

CLASS FullTimeEmployee EXTENDS EmployeeBase
VAR
    AnnualSalary : LREAL;
END_VAR

METHOD PUBLIC OVERRIDE GetMonthlySalary : LREAL
    GetMonthlySalary := AnnualSalary / 12.0;
END_METHOD
END_CLASS

CLASS ContractEmployee EXTENDS EmployeeBase
VAR
    HourlyPay : LREAL;
    MonthlyHours : LREAL;
END_VAR

METHOD PUBLIC OVERRIDE GetMonthlySalary : LREAL
    GetMonthlySalary := HourlyPay * MonthlyHours;
END_METHOD
END_CLASS

PROGRAM EmployeeDemo
VAR
    FullTime : FullTimeEmployee;
    Contract : ContractEmployee;
    Employee : IEmployee;
    Salary : LREAL;
END_VAR
    FullTime.AnnualSalary := 120000.0;
    Contract.HourlyPay := 80.0;
    Contract.MonthlyHours := 160.0;

    Employee := FullTime;
    Salary := Employee.GetMonthlySalary();

    Employee := Contract;
    Salary := Employee.GetMonthlySalary();
END_PROGRAM
