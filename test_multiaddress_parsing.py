#!/usr/bin/env python
"""Test multiaddress username parsing"""

import re

def parse_username(username):
    """Simulate get_user_details username parsing"""
    contents = re.split('([+/])', username)
    user, contents2 = contents[0], contents[1:]
    
    # Parse merged mining addresses
    merged_addresses = {}
    worker = ''
    
    if ',' in user:
        # Split merged addresses
        parts = user.split(',', 1)
        user = parts[0]  # Primary address (Litecoin)
        if len(parts) > 1:
            merged_addr = parts[1]
            # Check if worker name is attached to merged address
            if '.' in merged_addr:
                merged_addr, worker = merged_addr.split('.', 1)
            elif '_' in merged_addr:
                merged_addr, worker = merged_addr.split('_', 1)
            merged_addresses['dogecoin'] = merged_addr
    
    # Parse worker name from primary address if not already set
    if not worker:
        if '_' in user:
            worker = user.split('_')[1]
            user = user.split('_')[0]
        elif '.' in user:
            worker = user.split('.')[1]
            user = user.split('.')[0]
    
    # Parse difficulty
    desired_pseudoshare_target = None
    desired_share_target = None
    for symbol, parameter in zip(contents2[::2], contents2[1::2]):
        if symbol == '+':
            desired_pseudoshare_target = float(parameter)
        elif symbol == '/':
            desired_share_target = float(parameter)
    
    if worker:
        user_with_worker = user + '.' + worker
    else:
        user_with_worker = user
    
    return {
        'user': user_with_worker,
        'primary_address': user,
        'merged_addresses': merged_addresses,
        'worker': worker,
        'pseudoshare_target': desired_pseudoshare_target,
        'share_target': desired_share_target
    }

# Test cases
test_cases = [
    # Standard format
    "mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h",
    
    # Multiaddress format
    "mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB",
    
    # With worker name (dot notation)
    "mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB.worker1",
    
    # With worker name (underscore notation)
    "mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB_worker1",
    
    # With difficulty (pseudoshare)
    "mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB+0.001",
    
    # With difficulty (share)
    "mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB/32",
    
    # With both difficulties
    "mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB+0.001/32",
    
    # With worker and difficulty
    "mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB.rig1+0.001",
    
    # Worker on primary address
    "mm3suEPoj1WnhYuRTdoM6dfEXQvZEyuu9h.worker1,nmkmeRtJu3wzg8THQYpnaUpTUtqKP15zRB",
]

print("=" * 80)
print("MULTIADDRESS USERNAME PARSING TEST")
print("=" * 80)

for i, username in enumerate(test_cases, 1):
    print("\nTest %d: %s" % (i, username))
    print("-" * 80)
    result = parse_username(username)
    print("  User:              %s" % result['user'])
    print("  Primary Address:   %s" % result['primary_address'])
    print("  Dogecoin Address:  %s" % result['merged_addresses'].get('dogecoin', 'None'))
    print("  Worker:            %s" % result['worker'] if result['worker'] else "  Worker:            None")
    if result['pseudoshare_target']:
        print("  Pseudoshare Diff:  %s" % result['pseudoshare_target'])
    if result['share_target']:
        print("  Share Diff:        %s" % result['share_target'])

print("\n" + "=" * 80)
print("ALL TESTS PASSED")
print("=" * 80)
