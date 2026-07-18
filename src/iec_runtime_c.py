"""C runtime support emitted for IEC standard operations."""


BCD_TO_INT_RUNTIME = r'''static inline int16_t BCD_TO_INT(uint16_t value)
{
    int16_t result = 0;
    int16_t factor = 1;
    while (value != 0) {
        result += (int16_t)(value & 0x0fu) * factor;
        factor *= 10;
        value >>= 4;
    }
    return result;
}
'''

INT_TO_BCD_RUNTIME = r'''static inline uint16_t INT_TO_BCD(int16_t value)
{
    uint16_t result = 0;
    unsigned int shift = 0;
    while (value > 0) {
        result |= (uint16_t)(value % 10) << shift;
        value /= 10;
        shift += 4;
    }
    return result;
}
'''

C_RUNTIME_FUNCTIONS = {
    "BCD_TO_INT": BCD_TO_INT_RUNTIME,
    "INT_TO_BCD": INT_TO_BCD_RUNTIME,
}
