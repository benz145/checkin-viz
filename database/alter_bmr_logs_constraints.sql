ALTER TABLE bmr_logs
    DROP CONSTRAINT IF EXISTS bmr_logs_height_feet_check,
    DROP CONSTRAINT IF EXISTS bmr_logs_height_inches_check,
    DROP CONSTRAINT IF EXISTS bmr_logs_weight_lbs_check;

ALTER TABLE bmr_logs
    ADD CONSTRAINT bmr_logs_height_feet_check
        CHECK (height_feet >= 0 AND height_feet <= 7) NOT VALID,
    ADD CONSTRAINT bmr_logs_height_inches_check
        CHECK (height_inches >= 0 AND height_inches <= 12) NOT VALID,
    ADD CONSTRAINT bmr_logs_weight_lbs_check
        CHECK (weight_lbs > 0 AND weight_lbs <= 500) NOT VALID;
