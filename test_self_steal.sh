#!/bin/bash
# Test Self-Steal Condition (Exceeding Own Record)
# This script demonstrates when a user exceeds their own medal record

export PATH="/Users/benlang/.local/bin:$PATH"

echo "============================================================"
echo "Testing Self-Steal (Exceeding Own Record)"
echo "============================================================"
echo ""
echo "A self-steal happens when a user exceeds their own medal record."
echo "Example: User has T5 as highest tier, then checks in with T6"
echo ""
echo "Expected message:"
echo "  <@USER> exceeded their own 💪 Highest Weekly Tier!"
echo ""
echo "============================================================"
echo "Step 1: User checks in with T5 (earns highest_tier_week medal)"
echo "============================================================"
poetry run python3 test_medal_messages.py --user 218126977574502403 --message "T5 checkin" 2>&1 | grep -E "(✓|✗|earned|stole|exceeded|Check-in|Medal|FULL REPLY|Type:)" | head -20

echo ""
echo "============================================================"
echo "Step 2: Same user checks in with T6 (exceeds own record)"
echo "============================================================"
poetry run python3 test_medal_messages.py --user 218126977574502403 --message "T6 checkin" 2>&1 | grep -E "(✓|✗|earned|stole|exceeded|Check-in|Medal|FULL REPLY|Type:|SUMMARY)" | head -25

echo ""
echo "============================================================"
echo "Step 3: Verify the self-steal - check user's most recent check-in"
echo "============================================================"
poetry run python3 test_medal_messages.py --user 218126977574502403 2>&1 | grep -E "(✓|✗|earned|stole|exceeded|Check-in|Medal|FULL REPLY|Type:|exceeded their own)" | head -20

echo ""
echo "============================================================"
echo "Test Complete!"
echo "============================================================"
echo ""
echo "Expected result: User should have 'exceeded their own 💪 Highest Weekly Tier!'"

