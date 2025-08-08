// == Multipage Microsoft Form Auto-fill ==
function fillContributionForm() {
  console.log("=== Running Fill Script ===");

  // --- Load IDs ---
  let teamMemberIDs = JSON.parse(localStorage.getItem("teamMemberIDs")) || [];
  if (teamMemberIDs.length === 0) {
    for (let i = 1; i <= 7; i++) {
      let id = prompt(`Enter ID for team member ${i} (Your ID last):`);
      teamMemberIDs.push(id);
    }
    localStorage.setItem("teamMemberIDs", JSON.stringify(teamMemberIDs));
  }

  // --- Load Scores ---
  let scores = JSON.parse(localStorage.getItem("scores")) || [];
  if (scores.length === 0) {
    let remaining = 100;
    for (let i = 1; i <= 7; i++) {
      let score = parseInt(prompt(`Enter score for member ${i} (remaining ${remaining}%)`));
      if (isNaN(score) || score > 100 || score < 0) score = 0;
      scores.push(score);
      remaining -= score;
    }
    localStorage.setItem("scores", JSON.stringify(scores));
  }

  // --- Wait until inputs appear ---
  function waitForInputs(labelPart, callback) {
    const interval = setInterval(() => {
      let inputs = Array.from(document.querySelectorAll("input"))
        .filter(el => el.getAttribute("aria-label")?.includes(labelPart)
          || el.placeholder?.includes(labelPart));
      if (inputs.length > 0) {
        clearInterval(interval);
        callback(inputs);
      }
    }, 500);
  }

  // --- Fill IDs ---
  waitForInputs("Number must be between", idInputs => {
    waitForInputs("Please enter a number less than or equal to 100", scoreInputs => {
      console.log(`Found ${idInputs.length} ID fields, ${scoreInputs.length} score fields`);

      for (let i = 0; i < Math.min(idInputs.length, scoreInputs.length, 7); i++) {
        idInputs[i].value = teamMemberIDs[i];
        idInputs[i].dispatchEvent(new Event("input", { bubbles: true }));

        scoreInputs[i].value = scores[i];
        scoreInputs[i].dispatchEvent(new Event("input", { bubbles: true }));

        console.log(`Set ID ${teamMemberIDs[i]} → Score ${scores[i]}`);
      }

      // Set "Are you sure?" to Yes if it exists
      let yesRadio = document.querySelector('input[value="Yes"][type="radio"]');
      if (yesRadio) {
        yesRadio.checked = true;
        yesRadio.dispatchEvent(new Event("change", { bubbles: true }));
        console.log("Set 'Are you sure?' to Yes");
      }
    });
  });
}

// Click on Next and Run this function
fillContributionForm();
