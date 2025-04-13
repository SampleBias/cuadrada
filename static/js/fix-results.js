/**
 * Fix Results Display - Corrects display issues with review outcome messages
 * This script runs on page load and checks if the outcome message matches the actual review statuses
 */
document.addEventListener('DOMContentLoaded', function() {
    // Check if we're on the results page (has outcome message)
    const outcomeMessage = document.querySelector('.outcome-message');
    if (!outcomeMessage) return;

    // Only run this fix if we're on the results page and not in processing mode
    const isProcessing = document.querySelector('.loading-container');
    if (isProcessing) return;

    // Gather all review decisions
    const reviewCards = document.querySelectorAll('.review-card');
    if (!reviewCards.length) return;

    // Track actual review status
    let hasAccepted = false;
    let hasRejected = false;
    let hasRevision = false;
    let hasError = false;
    let totalReviews = 0;

    // Process all review cards to get the actual status
    reviewCards.forEach(card => {
        // Find the decision element
        const decisionEl = card.querySelector('.review-status');
        if (!decisionEl) return;

        totalReviews++;
        const decision = decisionEl.textContent.trim().toUpperCase();
        
        if (decision === 'ACCEPTED') {
            hasAccepted = true;
        } else if (decision === 'REJECTED') {
            hasRejected = true;
        } else if (decision === 'REVISION') {
            hasRevision = true;
        } else if (decision === 'ERROR') {
            hasError = true;
        }
    });

    // Determine the actual outcome
    let actualOutcome;
    if (hasError) {
        actualOutcome = 'error';
    } else if (hasAccepted && !hasRejected && !hasRevision) {
        // All accepted
        actualOutcome = 'accepted';
    } else if (hasRevision) {
        // At least one needs revision
        actualOutcome = 'revision';
    } else if (hasRejected) {
        // At least one rejection
        actualOutcome = 'rejected';
    }

    // Get the current displayed outcome
    const currentOutcome = outcomeMessage.classList.contains('rejected') ? 'rejected' :
                         outcomeMessage.classList.contains('revision') ? 'revision' :
                         outcomeMessage.classList.contains('accepted') ? 'accepted' : 'error';

    console.log(`Review status check: ${totalReviews} reviews found`);
    console.log(`Status: Accepted=${hasAccepted}, Rejected=${hasRejected}, Revision=${hasRevision}, Error=${hasError}`);
    console.log(`Current outcome: ${currentOutcome}, Actual outcome: ${actualOutcome}`);

    // If the displayed outcome doesn't match the actual outcome, fix it
    if (currentOutcome !== actualOutcome && actualOutcome) {
        console.log(`Fixing outcome display from ${currentOutcome} to ${actualOutcome}`);
        
        // Remove current classes
        outcomeMessage.classList.remove('rejected', 'revision', 'accepted', 'error');
        
        // Add the correct class
        outcomeMessage.classList.add(actualOutcome);
        
        // Update the content based on the correct outcome
        if (actualOutcome === 'accepted') {
            outcomeMessage.innerHTML = `
                <div class="outcome-icon">🌟</div>
                <h2>Absolutely Brilliant Work!</h2>
                <p>Pop the champagne! Your paper has impressed all our reviewers. This is the kind of research that makes the 
                   academic world go round. Download your certificate below and take a moment to bask in the glory!</p>
                <div class="outcome-quote">"Success is not the key to happiness. Happiness is the key to success. 
                   If you love what you are doing, you will be successful." - Albert Schweitzer</div>
            `;
        } else if (actualOutcome === 'revision') {
            outcomeMessage.innerHTML = `
                <div class="outcome-icon">✍️</div>
                <h2>So Close, Yet So Far!</h2>
                <p>Your paper shows great promise - it just needs a bit more polish! Think of it like a diamond in the rough. 
                   Take our reviewers' suggestions, give it some extra sparkle, and show us what you've got!</p>
                <div class="outcome-quote">"The difference between ordinary and extraordinary is that little extra." - Jimmy Johnson</div>
            `;
        } else if (actualOutcome === 'rejected') {
            outcomeMessage.innerHTML = `
                <div class="outcome-icon">💪</div>
                <h2>Keep That Research Spirit Burning!</h2>
                <p>Your paper didn't quite make it this time, but remember - every "no" is just a "yes" waiting to happen! 
                   Take the feedback from our reviewers, power up your research, and come back stronger!</p>
                <div class="outcome-quote">"Success is not final, failure is not fatal: it is the courage to continue that counts." - Winston Churchill</div>
            `;
        } else if (actualOutcome === 'error') {
            outcomeMessage.innerHTML = `
                <div class="outcome-icon">🔄</div>
                <h2>Oops! We Hit a Snag!</h2>
                <p>Don't worry - even AI reviewers need coffee breaks sometimes! Please use the retry button above to get that review back on track.</p>
            `;
        }
        
        console.log('Display fixed!');
    }
});
