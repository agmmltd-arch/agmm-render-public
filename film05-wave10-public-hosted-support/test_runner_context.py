#!/usr/bin/env python3
"""Positive workflow-context test plus required negative runner.job-env regression."""
from pathlib import Path
import unittest
from validate_runner_context import validate

WORKFLOW=Path(__file__).parents[1]/"film05-wave10-public-hosted-picture-proof.yml"

class RunnerContextTests(unittest.TestCase):
    def test_step_scope_runner_paths_are_accepted(self):
        validate(WORKFLOW.read_text(encoding="utf-8"))

    def test_runner_temp_in_job_env_is_rejected(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        marker="      EXPECTED_HEAD_SHA: ${{ inputs.expected_head_sha }}\n"
        self.assertIn(marker,text)
        bad=text.replace(marker,marker+"      BAD_PATH: ${{ runner.temp }}/invalid\n",1)
        with self.assertRaisesRegex(ValueError,"runner context or runner-local variables are unavailable in job-level env"):
            validate(bad)

    def test_initializer_must_be_the_first_step(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        needle="    steps:\n      - name: Initialize runner-local paths\n"
        replacement="    steps:\n      - name: Unexpected first step\n        run: echo no\n      - name: Initialize runner-local paths\n"
        self.assertIn(needle,text)
        with self.assertRaisesRegex(ValueError,"must be the first step"):
            validate(text.replace(needle,replacement,1))

    def test_runner_temp_shell_variable_in_job_env_is_rejected(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        marker="      EXPECTED_HEAD_SHA: ${{ inputs.expected_head_sha }}\n"
        bad=text.replace(marker,marker+"      BAD_PATH: $RUNNER_TEMP/private\n",1)
        with self.assertRaisesRegex(ValueError,"runner context or runner-local variables are unavailable in job-level env"):
            validate(bad)

    def test_missing_github_env_initializer_is_rejected(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        start=text.index("      - name: Initialize runner-local paths\n")
        end=text.index("      - name: Guard public repository",start)
        bad=text[:start]+text[end:]
        with self.assertRaisesRegex(ValueError,"must be the first step|initializer is missing"):
            validate(bad)

if __name__=="__main__": unittest.main(verbosity=2)
