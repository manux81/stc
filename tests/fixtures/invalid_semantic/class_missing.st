CLASS (* missing class name *)
	VAR PUBLIC
		p: INT := (* missing initializer value *) ;
	END_VAR
END_CLASS

FUNCTION SomeFuction 
	RETURN 13 (* superfluous literal *) ;
END_FUNCTION

FUNCTION SomeOtherFunction
	a := 12;
	CLASS (* superfluous keyword *)
END_FUNCTION

