// Start: Implementing jQuery Phone Validation https://www.jqueryscript.net/form/jQuery-International-Telephone-Input-With-Flags-Dial-Codes.html
var input = document.querySelector("#registerPhone"),
  errorMsg = document.querySelector("#registerPhoneError"),
  validMsg = document.querySelector("#registerPhoneValid");
var errorMap = ["Invalid number", "Invalid country code", "Too short", "Too long", "Invalid number"];

var iti = window.intlTelInput(input, {
	// Set initialCountry to 'auto' and pass in a function for geoIpLookup to perform a JSONP request to ipinfo.io, which returns the user's country based on their IP address.
	initialCountry: "auto",
	geoIpLookup: function(callback) {
		$.get('https://ipinfo.io', function() {}, "jsonp").always(function(resp) {
			var countryCode = (resp && resp.country) ? resp.country : "";
			callback(countryCode);
		});
	},
	excludeCountries: ["AU","DK","NL","RO","SG","AF","AS","BY","CN","CU","CW","CY","CD","ER","GR","GU","GW","IR","IQ","KP","LB","LR","LY","LI","MP","MH","FM","MM","AN","NG","PW","PR","RU","SO","SS","SD","SY","UA","US","VI","UM","KH","CA","CF","ET","GN","HT","LA","ML","MR","MU","PA","YE","TT","PL"],
	// Set onlyCountries option to just European country codes.
	/*	onlyCountries: ["ca","al","ad"], */
	 // Use the isValidNumber method (which utilises Google's libphonenumber) to validate the telephone number
	utilsScript: "https://lottoexpress.com/resources/js/utils.js?<%= time %>"
});

var reset = function() {
	input.classList.remove("error");
	errorMsg.innerHTML = "";
	errorMsg.classList.add("registerPhoneMsgHide");
	validMsg.classList.add("registerPhoneMsgHide");
};

input.addEventListener('blur', function() {
	reset();
	if (input.value.trim()) {
		if (iti.isValidNumber()) {
			validMsg.classList.remove("registerPhoneMsgHide");
		} else {
			input.classList.add("error");
			var errorCode = iti.getValidationError();
			errorMsg.innerHTML = errorMap[errorCode];
			errorMsg.classList.remove("registerPhoneMsgHide");
		}
	}
});

input.addEventListener('change', reset);
input.addEventListener('keyup', reset);