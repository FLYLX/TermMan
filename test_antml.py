import re, json, sys
tc_open = chr(60) + chr(97) + chr(110) + chr(116) + chr(109) + chr(108) + chr(58) + chr(116) + chr(111) + chr(111) + chr(108) + chr(95) + chr(99) + chr(97) + chr(108) + chr(108) + chr(62)
tri = chr(8883)
text = chr(0x8ba9)+chr(0x6211)+chr(0x5148)+chr(0x770b)+chr(0x770b) + tc_open + chr(109)+chr(99)+chr(112)+chr(95)+chr(108)+chr(111)+chr(99)+chr(97)+chr(108)+chr(95)+chr(108)+chr(105)+chr(115)+chr(116)+chr(95)+chr(106)+chr(111)+chr(98)+chr(115)+chr(40)+chr(41) + tri + tc_open + chr(109)+chr(99)+chr(112)+chr(95)+chr(108)+chr(111)+chr(99)+chr(97)+chr(108)+chr(95)+chr(114)+chr(101)+chr(97)+chr(100)+chr(95)+chr(116)+chr(97)+chr(115)+chr(107)+chr(95)+chr(119)+chr(111)+chr(114)+chr(107)+chr(102)+chr(108)+chr(111)+chr(119)+chr(40)+chr(41) + tri
print(repr(text))
pat = re.compile(r'<antml:tool_call>(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\((?P<args>[^)]*)\)')
matches = pat.findall(text)
print('Matches:', matches)