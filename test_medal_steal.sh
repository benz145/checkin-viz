#!/bin/bash
# Test Medal Steal Condition
# This script demonstrates how to test when one user steals a medal from another

export PATH="/Users/benlang/.local/bin:$PATH"

echo "============================================================"
echo "Testing Medal Steal Condition"
echo "============================================================"
echo ""
echo "Medals that CAN be stolen:"
echo "  - Highest Weekly Tier (💪)"
echo "  - Earliest Weekly Check-in (🌞)"
echo "  - Latest Weekly Check-in (🌚)"
echo "  - Highest Overall Tier (🏋)"
echo "  - Earliest Challenge Check-in (🌞)"
echo "  - Latest Challenge Check-in (🌚)"
echo ""
echo "Medals that CANNOT be stolen:"
echo "  - Gold Week (🏅)"
echo "  - Green Week (🟩)"
echo "  - First to Green (⭐)"
echo "  - All Gold (⭐)"
echo "  - All Green (❇️)"
echo ""
echo "============================================================"
echo "Step 1: User 1 checks in with T3"
echo "============================================================"
poetry run python3 test_medal_messages.py --user 217390830866923521 --message "T3 checkin" 2>&1 | grep -E "(✓|✗|earned|stole|Check-in|Medal|FULL REPLY|Type:)" | head -20

echo ""
echo "============================================================"
echo "Step 2: User 2 checks in with T5 (steals highest tier)"
echo "============================================================"
poetry run python3 test_medal_messages.py --user 218126977574502403 --message "T5 checkin" 2>&1 | grep -E "(✓|✗|earned|stole|Check-in|Medal|FULL REPLY|Type:)" | head -20

echo ""
echo "============================================================"
echo "Step 3: Verify the steal - check User 2's medal"
echo "============================================================"
poetry run python3 test_medal_messages.py --user 218126977574502403 2>&1 | grep -E "(✓|✗|earned|stole|Check-in|Medal|FULL REPLY|Type:|stolen from)" | head -20

echo ""
echo "============================================================"
echo "Test Complete!"
echo "============================================================"
echo ""
echo "Expected result: User 2 should have 'stole 💪 Highest Weekly Tier from <@USER1>!'"

