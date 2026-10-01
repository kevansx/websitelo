var NumberPicker = function(productInfo, getBonusOnly) {
	
    var minBall = 1;
    var maxBall = productInfo.MaxBallNumber;
    var minBonusBall = 1;
    var maxBonusBall = productInfo.MaxBonusBallNumber;
    var pickBallNumber = productInfo.PickBallNumber;
    var bonusBallNumber = productInfo.BonusBallNumber;

	//bonusOnly = true; will get only the bonus numbers for products w/o selectable bonus numbers
    var bonusOnly = getBonusOnly;

    this.getNumbers = function () {
        var numbers = bonusOnly ? getRandomNumbers(getRange(minBonusBall, maxBonusBall), bonusBallNumber) : getRandomNumbers(getRange(minBall, maxBall), pickBallNumber);
        return numbers;
    };

    this.getOtherNumbers = function (existArray) {

        var numberRange = bonusOnly ? getRange(minBonusBall, maxBonusBall) : getRange(minBall, maxBall);
       
        for (var j = 0; j < existArray.length; j++) {
            numberRange.splice($.inArray(existArray[j],numberRange) ,1);
        }
        var numbers = bonusOnly ? getRandomNumbers(numberRange, bonusBallNumber - existArray.length): getRandomNumbers(numberRange, pickBallNumber - existArray.length);
        return numbers.concat(existArray).sort(function(a, b) { return a - b; });
    };
   
    function getRandomNumbers(numberArray, count) {
        shuffle(numberArray);

        var nums = numberArray.slice(0, count);
        nums.sort(function(a, b) { return a - b; });

        return nums;
    };

    function getRange(min, max) {
        var numbers = [];
        for (var i = min; i <= max; i++) {
            numbers.push(i);
        }
        return numbers;
    }

    function shuffle(array) {
        var m = array.length, t, d;

        // While there remain elements to shuffle…
        while (m) {

            // Pick a remaining element…
            d = Math.floor(Math.random() * m--);

            // And swap it with the current element.
            t = array[m];
            array[m] = array[d];
            array[d] = t;
        }

        return array;
    }

    function unionArrays(a, b) {

        var newArray = a.slice();
        for (var i = 0; i < b.length; i++) {
                var val = b[i];

                if (newArray.indexOf(val) < 0)
                    newArray.push(val);
        }
        return newArray;
    }
};