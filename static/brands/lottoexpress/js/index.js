var findSyndicateWidth = $('body').outerWidth();
if(findSyndicateWidth < 360){
	$('#syndicateBoxes').animate( { scrollLeft: 100}, 500);
}

function setPaymentAddress(city,cityClass,country,countryClass,stateClass){
	$.post("/resources/php_functions/get-cities-from-cache.php", {	getSelectedCountry: country  },
	function(data, status){
		cityResults(data,city,cityClass,country,countryClass,stateClass);
	});
}

function cityResults(data,city,cityClass,country,countryClass,stateClass){
	$("."+cityClass).find('option').remove();
	$("."+countryClass).val(country);
	returnedCities = JSON.parse(data);
	var seloption = "";
	seloption += '<option value="">Select City</option>';
	let stateToCity = '';
	var returnedCities = $.map( returnedCities, function( value, key ) {
		if(value['cityName'] == city || value['cityCode'] == city){
			seloption += '<option value="'+value['cityCode']+'" extra-attr="'+value['stateCode']+'" selected>'+value['cityName']+'</option>';
			stateToCity = value['stateCode'];
		} else {
			seloption += '<option value="'+value['cityCode']+'" extra-attr="'+value['stateCode']+'">'+value['cityName']+'</option>';
		}

	});
	$("."+cityClass).append(seloption);
	getAvailableStates(country,stateClass);
}

function getAvailableStates(country,stateClass){
	$("."+stateClass).find('option').remove();
	$.post("/resources/php_functions/get-cities-from-cache.php", {
		getAvailableStates: country
	},
	function(data, status){
		returnedStates = JSON.parse(data);
		if(returnedStates.length > 0){
			$("."+stateClass).removeClass('disabledState');
			$("."+stateClass).addClass('required');
			$(".requiresState").show();
			console.log('show it');
		} else {
			$("."+stateClass).addClass('disabledState');
			$("."+stateClass).removeClass('required');
			$(".requiresState").hide();
			console.log('hide it');
		}
		var selStateoption = "";
		selStateoption += '<option value="">Select State</option>';
		var returnedStates = $.map( returnedStates, function( value, key ) {
			selStateoption += '<option value="'+value['stateCode']+'">'+value['stateName']+'</option>';
		});
		$("."+stateClass).append(selStateoption);
	});
}

$(".addressCity").on('change',function(){
	var stateCode = $(".addressCity").find("option:selected").attr('extra-attr');
	if(stateCode != ''){
		$('.addressState').val(stateCode);
	} else {
		$('.addressState').addClass('disabledState');
		$('.addressState').removeClass('required');
		$('.addressState').removeClass('error');
	}
});

var cookiePromptTest = false;

function maybeShowCookiePrompt() {
	// If user already accepted, ensure it's gone.
	if (!cookiePromptTest && checkCookie("cookiePrompt") === "on") {
		$("#cookie-prompt").remove();
		return;
	}
	if (!$("#cookieWarning").length) return;
	if ($("#cookie-prompt").length) return;

	$("#cookieWarning").before(
		'<div id="cookie-prompt"><div id="cookieContent"><p>This site uses cookies. By using our website, you agree to the use of cookies and other technologies as set out in the <a href="/privacy-policy" class="secondaryLink" onclick="cookieTermsPopUp(event)">Privacy & Cookie</a> policy.</p><button class="primaryFormButton closeCookieBanner" onclick="closeCookiePrompt(event)">Ok</button></div></div>'
	);
	$("#cookieWarning").show();
}

$(function () {
	if (cookiePromptTest || checkCookie("cookiePrompt") !== "on") {
		maybeShowCookiePrompt();
		// Some browsers restore pages from memory or do a fast repaint; ensure the banner "sticks"
		// unless the cookie has been set.
		setTimeout(maybeShowCookiePrompt, 300);
	}
});

// Handle bfcache restores / SPA-like fast navigations.
try {
	window.addEventListener("pageshow", function () {
		if (cookiePromptTest || checkCookie("cookiePrompt") !== "on") {
			maybeShowCookiePrompt();
		}
	});
} catch (e) {}
  
function closeCookiePrompt(e) {
	if (!e) var e = window.event;
    e.cancelBubble = true;
    if (e.stopPropagation) e.stopPropagation();
	if (!cookiePromptTest) {
		createCookie("cookiePrompt", "on", 1);
	}
	$("#cookie-prompt").remove();
	$(".navbar-default .container-fluid").css("top","0");
}

// Note: JavaScript cannot set HttpOnly cookies (this is a browser security feature).
// This function is used for non-sensitive preference cookies (e.g., cookiePrompt).
// HttpOnly cookies can only be set server-side and are used for sensitive session data.
function createCookie(name, value, days) {
	if (days) {
		var date = new Date();
		date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
		var expires = "; expires=" + date.toGMTString();
	}
	else var expires = "";
	// Legacy prod behavior uses SameSite=None; Secure.
	// On http://localhost (dev) Secure cookies won't set, so allow a fallback so the "Ok" button works.
	try {
		if (window.location && window.location.protocol === "https:") {
			document.cookie = name + "=" + value + expires + "; path=/; SameSite=None; Secure";
		} else {
			document.cookie = name + "=" + value + expires + "; path=/; SameSite=Lax";
		}
	} catch (e) {
		document.cookie = name + "=" + value + expires + "; path=/";
	}
}

function checkCookie(name) {
	var nameEQ = name + "=";
	var ca = document.cookie.split(';');
	for (var i = 0; i < ca.length; i++) {
		var c = ca[i];
		while (c.charAt(0) == ' ') c = c.substring(1, c.length);
		if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length, c.length);
	}
	return null;
}

function eraseCookie(name) {
	createCookie(name, "", -1);
}

function cookieTermsPopUp(e){
	if (!e) var e = window.event;
    e.cancelBubble = true;
    if (e.stopPropagation) e.stopPropagation();
}
	
$.getJSON("https://ipinfo.io/?callback=?", function (data) {
	$("#geoCountry,#geoSigninCountry").val(data.country);
	$("#registerCustomerIP").val(data.ip);
});

recaptcha = false;
fpRecaptch = false;
contactUsRecaptch = false;

var verifyCallback = function(response) {
	$("#recaptcha").removeClass("error");
	$('#recaptcha iframe').removeClass('recaptchaError');
	recaptcha = true;
};

var expiredCallback = function(response) {
	recaptcha = false;
};

var errorCallback = function(response) {
	recaptcha = true;
};

var verifyFPCallback = function(response) {
	$("#fp-recaptcha").removeClass("error");
	$('#fp-recaptcha iframe').removeClass('recaptchaError');
	fpRecaptch = true;
};

var expiredFPCallback = function(response) {
	fpRecaptch = false;
};

var errorFPCallback = function(response) {
	fpRecaptch = true;
};



var verifyContactUsCallback = function(response) {
	$("#contactUs-recaptcha").removeClass("error");
	$('#contactUs-recaptcha iframe').removeClass('recaptchaError');
	contactUsRecaptch = true;
};

var expiredContactUsCallback = function(response) {
	contactUsRecaptch = false;
};

var errorContactUsCallback = function(response) {
	contactUsRecaptch = true;
};

function loadRecaptcha(){
	if ($('script[src="https://www.google.com/recaptcha/api.js?onload=onloadCallback&render=explicit"]').length == 0) {
		var s = document.createElement("script");
		s.type = "text/javascript";
		s.src = "https://www.google.com/recaptcha/api.js?onload=onloadCallback&render=explicit";
		$("body").append(s);
	}
}
  
var onloadCallback = function() {
	let registerCaptcha = document.getElementById("recaptcha");
	let fpCaptcha = document.getElementById("fp-recaptcha");
	let contactCaptcha = document.getElementById("contactUs-recaptcha");
	if(registerCaptcha){
		grecaptcha.render('recaptcha', {
			'sitekey' : '6LeQKjUaAAAAAPvzFqJ6yUwjtiPXQSGSNCuiR8su',
			'callback' : verifyCallback,
			'expired-callback' : expiredCallback,
			'error-callback' : errorCallback
		});
	}
	if(fpCaptcha){
		grecaptcha.render('fp-recaptcha', {
			'sitekey' : '6LeQKjUaAAAAAPvzFqJ6yUwjtiPXQSGSNCuiR8su',
			'callback' : verifyFPCallback,
			'expired-callback' : expiredFPCallback,
			'error-callback' : errorFPCallback
		});
	}
	if(contactCaptcha){
		grecaptcha.render('contactUs-recaptcha', {
			'sitekey' : '6LeQKjUaAAAAAPvzFqJ6yUwjtiPXQSGSNCuiR8su',
			'callback' : verifyContactUsCallback,
			'expired-callback' : expiredContactUsCallback,
			'error-callback' : errorContactUsCallback
		});
	}
};

if(!(window.__wlDisableLegacySessionPolling === true)){
	setInterval(function(){
	    logout();
	},61000 * 8);
}

function logout(){
	$.get("/resources/php_functions/session.php", function(data, status){
		if(JSON.parse(data) === "inactive"){
			redirect();
		}
	});
}

function redirect(){
	$("#sessionExpiringPopUp,#overlay").show();
	var timeleft = 5;
	var downloadTimer = setInterval(function(){
		if(timeleft <= 0){ clearInterval(downloadTimer); timeleft = 5; }
		$("#sessionExpireCounter").html("Your session will expire in " + timeleft + " seconds");
		timeleft -= 1;
	}, 1000);
	setTimeout(function() {
		var isClicked = $('#resetSession').data('clicked');
		if( isClicked == 'no') {
			document.location = "/logout?status=force-logout";
		} else {
			$('#resetSession').data('clicked', 'no');
		}
	}, 5000);
}

$('#resetSession').on('click', function() {
	$(this).data('clicked', 'yes');
	$("#sessionExpiringPopUp,#overlay").hide();
	resetSessionPost();
});

function resetSessionPost(){
	$.post("/resources/php_functions/session.php", {
		resetSession: true
	},
	function(data, status){
	});
}

var sessionTimeOut = 1;
var timeInterval = 10 * 1000;

if(!(window.__wlDisableLegacySessionPolling === true)){
	setInterval(checkSession, timeInterval);
}

$(document).ready(function () {
	renewSession();
	
	$(window).scroll(function(){
	   renewSession();
	});
	
	$("body").mouseup(function () {
		renewSession();
	});
	
	$("body").scroll(function () {
		renewSession();
	});
	
	$("input").blur(function () {
		renewSession();
	});

	$("input").focus(function () {
		renewSession();
	});
});

function renewSession() {
	sessionTimeOut = 0;  
}

function checkSession() {
	if(sessionTimeOut == 0) {
		$.post("/resources/php_functions/api/api-active-session.php", {
			activeSession: true
		},
		function(data, status){
			if((status == "success") && (data == 200 || data == "")){
				sessionTimeOut = 1;
			} else if((status == "success") && (data == "wait")){
				sessionTimeOut = 0;
			} else {
				sessionTimeOut = 0;
			}
		});
	} else {
		sessionTimeOut = sessionTimeOut + 1;
	}
}	

if(!(window.__wlDisableLegacySessionPolling === true)){
	setInterval(function(){
	    checkSessionStillValid();
	},1000);
}

function checkSessionStillValid() {
	$.post("/resources/php_functions/check-session.php", {
		checkSessionStatus: true
	},
	function(data, status){
		if(data == "not set"){
			if($("#realityCheckPopup").length > 0) {
				document.location = "/logout";
			}
		}
	});
	
}

$('.shoppingCartAlert').on('click', function (){
	$("#itemInShoppingCartPopUp,#overlay").show();
	$("body").css("overflow","auto");
});

$('.savedShoppingCartForm').on('submit', function(){
	$("#logoutSavedShoppingCartForm").attr("disabled", "disabled");
	$("#bannerSavedShoppingCartForm").attr("disabled", "disabled");
	$('.loader').show();
});

$('#alertSavedShoppingCart .formPopupHeaderClose').on('click', function(){
	$('#alertSavedShoppingCart').hide();
});

$("#closeItemInCartBanner").click(function(){
	$.post("/resources/php_functions/saved-item-in-cart.php", {
		unsetSavedCartSession: true
	},
	function(data, status){
	});
});

$(".showShoppingCartBanner").on("click", function(){
	$.post("/resources/php_functions/saved-item-in-cart.php", {
		showShoppingCartBanner: true
	},
	function(data, status){
	});
});

$(".cancelPlay").on("click", function(){
	$('.loader,#overlay').show();
	var eventId = event.target.id;
	$.post("/resources/php_functions/remove-shopping-cart.php", {
		cancelPlay: true
	},
	function(data, status){
		if(data == 1){
			if(eventId == "cancelBetSubscriptionBannerLink"){
				location.reload();
			} else if(eventId == "cancelBetSubscriptionLogoutLink"){
				document.location = "/logout";
			}
		} else {
			$('.loader').hide();
			$("#fatalErrorMessage").show();
		}
	});
});

$(".bannerPromoPlayNow").click(function() {
    $([document.documentElement, document.body]).animate({
        scrollTop: $("#lotterySection").offset().top
    }, 2000);
});

$(".accordionLines").off('click');
$(".accordionLines").on('click', function () {
	var jQarrow = $(this).find(".glyphicon");
	if ($(this).hasClass('active')) {
		$(this).removeClass('active');
		jQarrow.removeClass("open");
	} else {
		$(this).addClass('active');
		jQarrow.addClass("open");
	}
});	

$(".addFundsContent .custom-select-wrapper").on('click',function(){
	this.querySelector('.custom-select').classList.toggle('open');
	currentCardClass = $(".custom-select__trigger span span").attr('class');
	$(".custom-options .custom-option").each(function(){
		getallCards = $(this).find('span').attr('class');
	});
});

$(".addressCountry").on("change",function(){
	billingCountry = $(this).val();
	setPaymentAddress("","addressCity",billingCountry,"addressCountry","addressState");
});

$('input[name="changeBillingAdd"]').click(function(){
	if($(this).is(":checked")){
		$(".billingAddressInfo").hide();
	} else if($(this). is(":not(:checked)")){
		$(".billingAddressInfo").show();
	}
});

$(".addFundsConvert").focusout(function(){
	if ($('.addFundsEchangeRate').length){
		let amount = $('.addFundsConvert').val();
		let exchange = $('.addFundsEchangeRate').html();
		let convertAmount = (amount * exchange).toFixed(2);
		$('.addFundsAltCurrencyAmount').html(convertAmount);
		let inputAmount = parseFloat(amount).toFixed(2);
		$('.addfundsAmountToBeConverted').html(inputAmount);
	}
});

jQuery.validator.addMethod(
    "money",
    function(value, element) {
        var isValidMoney = /^\d{0,6}(\.\d{0,2})?$/.test(value);
        return this.optional(element) || isValidMoney;
    },
    "Insert "
);

$('.creditCardNumber').keyup(function() {
  var foo = $(this).val().split("-").join("");
  if (foo.length > 0) {
    foo = foo.match(new RegExp('.{1,4}', 'g')).join("-");
  }
  $(this).val(foo);
});

addFundsMinDepositAmount = 5;
$('#newCCAddFundsForm').each(function() {
	$(this).validate({
		rules: {
			newCCAddFundsCCNumber: {
				required: true,
				creditcard: true
			},
			newCCAddFundsAmount: {
				money: true,
				required: true,
				range: [addFundsMinDepositAmount, depositLimit]
			}
		  },
		messages: {
			newCCAddFundsName: "",
			newCCAddFundsCCNumber: "",
			newCCAddFundsCVV: "",
			newCCAddFundsExpiryMM: "",
			newCCAddFundsExpiryYY: "",
			newCCAddFundsAmount: "",
			country: "",
			address: "",
			postcode: "",
			city: "",
			state: ""
		}
	});
});

$('input[name="addFundsTerms"]').click(function(){
	$("#addFundsTerms").removeClass("redText");
	$("#addFundsTerms .redesignCheckmark").css("border-color","#FFFFFF");
});

$('#newCCAddFundsForm').submit(function() {
	if(!$('input[name="addFundsTerms"]', this).is(':checked')){	
		$("#addFundsTerms").addClass("redText");
		$("#addFundsTerms .redesignCheckmark").css("border-color","red");
		return false;
	}
	if($(this).valid()) {
		let name = $('input[name="newCCAddFundsName"]').val();
		let number = $('input[name="newCCAddFundsCCNumber"]').val().replace(new RegExp('-', 'g'),"");
		if(name === number){
			$('input[name="newCCAddFundsName"]').addClass('error');
			alert('Cardholder Name and Card Number cannot be the same');
			return false;
		}
		$("#addFundsSubmitNewCC").attr("disabled", "disabled");
		$('.loader').show();
		return true;
	}
});

$('#liveCCAddFundsForm').each(function() {
	$(this).validate({
		rules: {
			liveCCAddFundsAmount: {
			  required: true,
			  money: true,
			  range: [addFundsMinDepositAmount, depositLimit]
			}
		  },
		messages: {
			liveCCAddFundsCVV: "3 digit CVV number required",
			liveCCAddFundsAmount: "",
			liveCCAddFundsExpiryMM: "",
			liveCCAddFundsExpiryYY: "",
			liveCCAddFundsCountry: "",
			liveCCAddFundsAddress: "",
			liveCCAddFundsAddressPostCode: "",
			liveCCAddFundsAddressCity: ""
		}
	});
});

$('#liveCCAddFundsForm').submit(function() {
	if($(this).valid()) {
		$("#addFundsSubmit").attr("disabled", "disabled");
		$('.loader').show();
		return true;
	}
});

if($("#liveCCAddFundsForm").length > 0){
	$(".addCardToFile").hide();
}

$(".inputTopUpAmount").focusout(function(){
	var getAmount = $(this).val();
	var getPreDefinedAmount = $(".topUpAmountActive .addFundsAmount").html() + '.00';
	if(getAmount != getPreDefinedAmount){
		$("#addFundsAmounts li").removeClass('topUpAmountActive');
	}
	if(!$.isNumeric($(this).val()))
	$(this).val('0').trigger('change');
	$(this).val(parseFloat($(this).val(), 10).toFixed(2));
	confirmCorrectAmount($(this).val());
});

function replaceAddFundsValue(val,id){
	if(confirmCorrectAmount(val) == true){
		$("#newCCAddFundsAmount").val(val);
		$("#liveCCAddFundsAmount").val(val);
		$("#addFundsAmounts li").removeClass("topUpAmountActive");
		$("#"+id).addClass("topUpAmountActive");
		$("#newCCAddFundsAmount").focusout();
		$("#liveCCAddFundsAmount").focusout();
	} else {
		$("#newCCAddFundsAmount").val('');
		$("#liveCCAddFundsAmount").val('');
		$("#addFundsAmounts li").removeClass("topUpAmountActive");
	}
}

function confirmCorrectAmount(amount){
	if(amount < addFundsMinDepositAmount){
		$("#newCCAddFundsAmount").val(0);
		$("#liveCCAddFundsAmount").val(0);
		$(".addFundsDepositError").html("Minimum deposit of "+addFundsMinDepositAmount+".00");
		return false;
	} else if(amount > depositLimit){
		$("#newCCAddFundsAmount").val("");
		$("#liveCCAddFundsAmount").val("");
		$(".addFundsDepositError").html(amount+" is over your Deposit Limit of "+depositLimit.toFixed(2)+"<br><a class='tertiaryLink' href='/account#showAccountLimits'>Click Here To Adjust Your Limits</a>");
		return false;
	} else {
		$(".addFundsDepositError").html("");
		$('.inputTopUpAmount').val(amount);
		return true;
	}
}

$("#addFunds .custom-option").on('click',function(){
	selectedContent = $(this).html();
	$('.custom-select__trigger span').html(selectedContent);
	getValue = $(this).attr("data-value");
	$('input[name="liveCCAddFundsCCPosition"]').val(getValue);
});

$('input[name="liveCCAddFundsEditCard"]').click(function(){
	if($(this).is(":checked")){
		$('#addFunds .editCardFields').show();
	} else if($(this). is(":not(:checked)")){
		$('#addFunds .editCardFields').hide();
	}
});

function populateAddFundsForm(expMM,expYY,billingCountry,billingAddress,billingCity,billingZip){
	$('select[name="liveCCAddFundsExpiryMM"]').val(expMM);
	$('select[name="liveCCAddFundsExpiryYY"]').val(expYY);
	$('input[name="liveCCAddFundsAddress"]').val(billingAddress);
	$('input[name="liveCCAddFundsAddressPostCode"]').val(billingZip);
	setPaymentAddress(billingCity,"liveCCAddFundsAddressCity",billingCountry,"liveCCAddFundsCountry");
}

$("#liveCCAddFundsCountry").on("change",function(){
	billingCountry = $(this).val();
	setPaymentAddress("","liveCCAddFundsAddressCity",billingCountry,"liveCCAddFundsCountry");
});

$('#acctCCAddPromoFundsForm').each(function() {
	$(this).validate({
		rules: {
			liveCCAddBetFundsAmount: {
			  required: true,
			  money: true,
			  range: [addFundsForBetMinDepositAmount, depositLimit]
			}
		  },
		messages: {
			liveCCAddBetFundsCVV: "3 digit CVV number required",
			liveCCAddBetFundsAmount: "",
			liveCCAddBetFundsExpiryMM: "",
			liveCCAddBetFundsExpiryYY: "",
			liveCCAddBetFundsCountry: "",
			liveCCAddBetFundsAddress: "",
			liveCCAddBetFundsAddressPostCode: "",
			liveCCAddBetFundsAddressCity: ""
		}
	});
});

$('#acctCCAddPromoFundsForm').submit(function() {
	if($(this).valid()) {
		$("#addFundsForPromoSubmit").attr("disabled", "disabled");
		$('.loader').show();
        return true;	
	}
});

if($("#acctCCAddPromoFundsForm").length > 0){
	$(".addCardToFile").hide();
}

$('#newCCAddPromoFundsForm').each(function() {
	$(this).validate({
		rules: {
			newCCAddBetFundsCCNumber: {
				required: true,
				creditcard: true
			},
			newCCAddBetFundsAmount: {
			  required: true,
			  money: true,
			  range: [addFundsForBetMinDepositAmount, depositLimit]
			}
		  },
		messages: {
			newCCAddBetFundsName: "",
			newCCAddBetFundsCCNumber: "",
			newCCAddBetFundsCVV: "",
			newCCAddBetFundsExpiryMM: "",
			newCCAddBetFundsExpiryYY: "",
			newCCAddBetFundsAmount: "",
			country: "",
			address: "",
			postcode: "",
			city: "",
			state: ""
		}
	});
});

$('#newCCAddPromoFundsForm').submit(function() {
	if($(this).valid()) {
		let name = $('input[name="newCCAddBetFundsName"]').val();
		let number = $('input[name="newCCAddBetFundsCCNumber"]').val().replace(new RegExp('-', 'g'),"");
		if(name === number){
			$('input[name="newCCAddBetFundsName"]').addClass('error');
			alert('Cardholder Name and Card Number cannot be the same');
			return false;
		}
		$("#newCCAddPromoFundsSubmit").attr("disabled", "disabled");
		$('.loader').show();
		return true;	
	}
});

function populateAddFundsForPromoForm(expMM,expYY,billingCountry,billingAddress,billingCity,billingZip){
	$('select[name="liveCCAddBetFundsExpiryMM"]').val(expMM);
	$('select[name="liveCCAddBetFundsExpiryYY"]').val(expYY);
	$('input[name="liveCCAddBetFundsAddress"]').val(billingAddress);
	$('input[name="liveCCAddBetFundsAddressPostCode"]').val(billingZip);	
	setPaymentAddress(billingCity,"acctCCAddPromoFundsAddressCity",billingCountry,"acctCCAddPromoFundsCountry");
}

$("#addFundsForPromo .custom-option").on('click',function(){
	selectedContent = $(this).html();
	$('.custom-select__trigger span').html(selectedContent);
	getValue = $(this).attr("data-value");
	$('input[name="liveCCAddBetFundsCCPosition"]').val(getValue);
});

$("#acctCCAddPromoFundsCountry").on("change",function(){
	billingCountry = $(this).val();
	setPaymentAddress("","acctCCAddPromoFundsAddressCity",billingCountry,"acctCCAddPromoFundsCountry");
});

$('#newCCAddFundsForBetForm').each(function() {
	$(this).validate({
		rules: {
			newCCAddBetFundsCCNumber: {
				required: true,
				creditcard: true
			},
			newCCAddBetFundsAmount: {
			  required: true,
			  money: true,
			  range: [addFundsForBetMinDepositAmount, depositLimit]
			}
		  },
		messages: {
			newCCAddBetFundsName: "",
			newCCAddBetFundsCCNumber: "",
			newCCAddBetFundsCVV: "",
			newCCAddBetFundsExpiryMM: "",
			newCCAddBetFundsExpiryYY: "",
			newCCAddBetFundsAmount: "",
			country: "",
			address: "",
			postcode: "",
			city: "",
			state: ""
		}
	});
});

$('#newCCAddFundsForBetForm').submit(function() {
	if(!$('input[name="addFundsTerms"]', this).is(':checked')){	
		$("#addFundsTerms").addClass("redText");
		$("#addFundsTerms .redesignCheckmark").css("border-color","red");
		return false;
	}
	if($(this).valid()) {
		let name = $('input[name="newCCAddBetFundsName"]').val();
		let number = $('input[name="newCCAddBetFundsCCNumber"]').val().replace(new RegExp('-', 'g'),"");
		if(name === number){
			$('input[name="newCCAddBetFundsName"]').addClass('error');
			alert('Cardholder Name and Card Number cannot be the same');
			return false;
		}
		$("#addFundsForBetNewCCSubmit").attr("disabled", "disabled");
		$('.loader').show();
		return true;	
	}
});

$('#liveCCAddFundsForBetForm').each(function() {
	$(this).validate({
		rules: {
			liveCCAddBetFundsAmount: {
			  required: true,
			  money: true,
			  range: [addFundsForBetMinDepositAmount, depositLimit]
			}
		  },
		messages: {
			liveCCAddBetFundsCVV: "3 digit CVV number required",
			liveCCAddBetFundsAmount: "",
			liveCCAddBetFundsExpiryMM: "",
			liveCCAddBetFundsExpiryYY: "",
			liveCCAddBetFundsCountry: "",
			liveCCAddBetFundsAddress: "",
			liveCCAddBetFundsAddressPostCode: "",
			liveCCAddBetFundsAddressCity: ""
		}
	});
});

$('#liveCCAddFundsForBetForm').submit(function() {
	if($(this).valid()) {
		$("#addFundsForBetSubmit").attr("disabled", "disabled");
		$('.loader').show();
        return true;	
	}
});

if($("#liveCCAddFundsForBetForm").length > 0){
	$(".addCardToFile").hide();
}

$(".inputTopUpBetAmount").focusout(function(){
	var getAmount = $(this).val();
	var getPreDefinedAmount = $(".topUpAmountActive .addFundsAmount").html() + '.00';
	if(getAmount != getPreDefinedAmount){
		$("#addBetFundsAmounts li").removeClass('topUpAmountActive');
	}
	if(!$.isNumeric($(this).val()))
	$(this).val('0').trigger('change');
	$(this).val(parseFloat($(this).val(), 10).toFixed(2));
	confirmCorrectAmountForBet($(this).val());
});

function replaceAddBetFundsValue(val,id){
	if(confirmCorrectAmountForBet(val) == true){
		$("#newCCAddBetFundsAmount").val(val);
		$("#liveCCAddBetFundsAmount").val(val);
		$("#addBetFundsAmounts li").removeClass("topUpAmountActive");
		$("#"+id).addClass("topUpAmountActive");
		$("#newCCAddBetFundsAmount").focusout();
		$("#liveCCAddBetFundsAmount").focusout();
	} else {
		$("#newCCAddBetFundsAmount").val('');
		$("#liveCCAddBetFundsAmount").val('');
		$("#addBetFundsAmounts li").removeClass("topUpAmountActive");
	}
}

function confirmCorrectAmountForBet(amount){
	var minimumDeposit = 5;
	if(amount < minimumDeposit || amount < balanceOwing){
		$("#newCCAddBetFundsAmount").val(0);
		$("#liveCCAddBetFundsAmount").val(0);
		$("#liveCCAddBetFundsAmount,#newCCAddBetFundsAmount").addClass('error');
		if(balanceOwing > minimumDeposit){
			$(".depositError").html("Minimum deposit of "+balanceOwing.toFixed(2)+" is required to complete this transaction.");
		} else {
			$(".depositError").html("Minimum deposit of "+minimumDeposit+".00");
		}
		return false;
	} else if(amount > depositLimit){
		$("#newCCAddBetFundsAmount").val("");
		$("#liveCCAddBetFundsAmount").val("");
		$(".depositError").html(amount+" is over your Deposit Limit of "+depositLimit.toFixed(2)+"<br><a class='tertiaryLink' href='/account#showAccountLimits'>Click Here To Adjust Your Limits</a>");
		return false;
	} else {
		$(".depositError").html("");
		$(".inputTopUpBetAmount.error").removeClass("error");
		$(".inputTopUpBetAmount").val(amount);
		return true;
	}
}


$("input[data-type='currency']").on({
	keyup: function() {
	  formatCurrency($(this));
	  $("#addFundsAmounts li").removeClass("topUpAmountActive");	
	  $("#addBetFundsAmounts li").removeClass("topUpAmountActive");
	},
	blur: function() { 
	  formatCurrency($(this), "blur");
	  $("#addFundsAmounts li").removeClass("topUpAmountActive");
	  $("#addBetFundsAmounts li").removeClass("topUpAmountActive");
	}
});


function formatNumber(n) {
  return n.replace(/\D/g, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

function formatCurrency(input, blur) {
	var input_val = input.val();
	if (input_val === "") { return; }
	var original_len = input_val.length;
	var caret_pos = input.prop("selectionStart");
	if (input_val.indexOf(".") >= 0) {
		var decimal_pos = input_val.indexOf(".");
		var left_side = input_val.substring(0, decimal_pos);
		var right_side = input_val.substring(decimal_pos);
		left_side = formatNumber(left_side);
		right_side = formatNumber(right_side);
		if (blur === "blur") {
			right_side += "00";
		}
		right_side = right_side.substring(0, 2);
		input_val = left_side + "." + right_side;
	} else {
		input_val = formatNumber(input_val);
		input_val = input_val;
		if (blur === "blur") {
			input_val += ".00";
		}
	}
	input.val(input_val);
	var updated_len = input_val.length;
	caret_pos = updated_len - original_len + caret_pos;
	input[0].setSelectionRange(caret_pos, caret_pos);
}

$(".paymentTopUpMethods").on('click', function () {
	if($('.additionalPaymentOptions').is(":visible")){
		$(".additionalPaymentOptions,.topUpPaymentOverlay").hide();
		$("#ccTopUpMethod").removeClass("ccTopUpMethodActive");
		$(".paymentTopUpMethods").removeClass("active");
		$(".paymentTopUpMethods .glyphicon").removeClass("open");
	} else {
		$(".additionalPaymentOptions,.topUpPaymentOverlay").css("display","inline-block");
		$("#ccTopUpMethod").addClass("ccTopUpMethodActive");
		$(".paymentTopUpMethods").addClass("active");
		$(".paymentTopUpMethods .glyphicon").addClass("open");
	}
});

$(".topUpPaymentOverlay").on('click', function () {
	$(".additionalPaymentOptions,.infoWindow").hide();
	$(".topUpPaymentOverlay").hide().css("z-index","3");
	$("#ccTopUpMethod").removeClass("ccTopUpMethodActive");
	$(".paymentTopUpMethods").removeClass("active");
	$(".paymentTopUpMethods .glyphicon").removeClass("open");
});

$(".useReplacePaymentMethod").on('click', function () {
	$(".cardOnFile").hide();
	$(".addCardToFile").show();
});

$(".useExistingCardOption").on('click', function () {
	$(".cardOnFile").show();
	$(".addCardToFile").hide();
});

$("#addFundsForBet .custom-option").on('click',function(){
	selectedContent = $(this).html();
	$('.custom-select__trigger span').html(selectedContent);
	getValue = $(this).attr("data-value");
	$('input[name="liveCCAddBetFundsCCPosition"]').val(getValue);
});

$('input[name="liveCCAddBetFundsEditCard"]').click(function(){
	if($(this).is(":checked")){
		$('.editCardFields').show();
	} else if($(this). is(":not(:checked)")){
		$('.editCardFields').hide();
	}
});

$('input[name="liveCCAddBetFundsEditCardAdd"]').click(function(){
	if($(this).is(":checked")){
		$('.editBillingAddressInfo').show();
	} else if($(this). is(":not(:checked)")){
		$('.editBillingAddressInfo').hide();
	}
	isCitySet("liveCCAddBetFundsAddressCity","liveCCAddBetFundsPositionOneCity","liveCCAddBetFundsCountry");
});

function populateAddFundsForBetForm(expMM,expYY,billingCountry,billingAddress,billingCity,billingZip){
	$('select[name="liveCCAddBetFundsExpiryMM"]').val(expMM);
	$('select[name="liveCCAddBetFundsExpiryYY"]').val(expYY);
	$('input[name="liveCCAddBetFundsAddress"]').val(billingAddress);
	$('input[name="liveCCAddBetFundsAddressPostCode"]').val(billingZip);	
	setPaymentAddress(billingCity,"liveCCAddBetFundsAddressCity",billingCountry,"liveCCAddBetFundsCountry");
}

$("#liveCCAddBetFundsCountry").on("change",function(){
	billingCountry = $(this).val();
	setPaymentAddress("","liveCCAddBetFundsAddressCity",billingCountry,"liveCCAddBetFundsCountry");
});

$(".accordion header").off('click');
$(document).on('click','.accordion header',function(){
	var jQarrow = $(this).find(".glyphicon");
	if ($(this).hasClass('active')) {
		$(this).removeClass('active');
		jQarrow.removeClass("open");
	} else {
		$(this).addClass('active');
		jQarrow.addClass("open");
	}
});	
	
$('body').click( function() {
	if($("#mobileMenuButtonClose").is(":visible")){
		$('.mobile-nav-dropdown,.navbarHeaderLogo,#mobileMenuButtonClose,#overlay').hide();
		$(".navbar-header,#mobileMenuButton").show();
		$("#overlay").css("z-index","4")
		$("body").css("overflow","auto");
	}
});

$('#forgotPasswordFormPopUp,.viewSyndicateLines,.infoButton,#mobileMenuButton,.mobile-nav-dropdown,#paymentForSubscriptionFormPopUp,.infoWindow,#realityCheckPopup').click( function(e) {
    e.stopPropagation();
});

function formPopupHeaderClose(id){
	$("#"+id).hide();
	if($(".alertWindow,.formPopup").is(":visible")){
	} else {
		$("#overlay").hide();
	}
}

$(".infoWindowHeaderClose").click(function(){
	$("#overlay").hide();
	$(".infoWindow,.topUpPaymentOverlay").hide();
	$(".topUpPaymentOverlay").hide().css("z-index","3");
});

$("body").mouseup(function(e){
	$('.loggedInDetails').unbind('click').on('click', function (event){ 
		if($('.loggedInDetails').hasClass('accountDropdownActive')){
			$('.loggedInDetails').removeClass('accountDropdownActive');
		} else {
			$(this).addClass('accountDropdownActive');
		}
	});
	var rightMenuContent = $(".accountDropdownActive");
	if(e.target.id != rightMenuContent.attr('id') && !rightMenuContent.has(e.target).length){
		$('.loggedInDetails').removeClass('accountDropdownActive');
	}
});

$(".mobileMenuButton").click(function() {
	if($(".mobile-nav-dropdown").is(":visible")){
		$(".mobile-nav-dropdown,.navbarHeaderLogo,#mobileMenuButtonClose,#overlay").hide();
		$(".navbar-header,#mobileMenuButton").show();
		$("#overlay").css("z-index","4");
		$("body").css("overflow","auto");
	} else {
		$(".mobile-nav-dropdown,.navbarHeaderLogo,#mobileMenuButtonClose,#overlay").show();
		$("#overlay").css("z-index","3");
		$("body").css("overflow","hidden");
		$(".navbar-header,#mobileMenuButton").hide();
		if($("#cookie-prompt").is(":visible")){
			var cookieHeight = $("#cookie-prompt").height();
			$(".mobile-nav-dropdown").css("max-height","calc(87vh - "+cookieHeight+"px)");
		}		
	}
});

$(".singleLotteryNav").click(function() {
	if($(".singleLotteryNavList").is(":visible")){
		$(".singleLotteryNavList").hide();
		$(".singleLotteryNav").removeClass('lotteryNavListOpen');
	} else {
		$(".singleLotteryNavList").show();
		$(".singleLotteryNav").addClass('lotteryNavListOpen');
		$(".syndicateLotteryNavList").hide();
	}
});

$(".promotionsNav").click(function() {
	if($(".promotionNavList").is(":visible")){
		$(".promotionNavList").hide();
		$(".promotionsNav").removeClass('lotteryNavListOpen');
	} else {
		$(".promotionNavList").show();
		$(".promotionsNav").addClass('lotteryNavListOpen');
	}
});

$(".lotteryResultsNav").click(function() {
	if($(".lotteryResultsList").is(":visible")){
		$(".lotteryResultsList").hide();
		$(".lotteryResultsNav").removeClass('lotteryNavListOpen');
	} else {
		$(".lotteryResultsList").show();
		$(".lotteryResultsNav").addClass('lotteryNavListOpen');
	}
});

$(".syndicateLotteryNav").click(function() {
	if($(".syndicateLotteryNavList").is(":visible")){
		$(".syndicateLotteryNavList").hide();
	} else {
		$(".syndicateLotteryNavList").show();
		$(".singleLotteryNavList").hide();
	}
});

var lastScrollTop = 0;
$(window).scroll(function(event){
	var st = $(this).scrollTop();
	if(st > lastScrollTop){
		$("#cookie-prompt,.navbar .container-fluid").addClass("container-fixed-position");
		if(($("#cookie-prompt").is(":visible")) && ($(".mobile-nav").is(":visible"))){
			var cookieHeight = $("#cookie-prompt").height();
			$(".navbar-default .container-fluid").css("top",cookieHeight+"px");
		}
	}
	if(st == 0){
		$("#cookie-prompt,.navbar .container-fluid").removeClass("container-fixed-position");
		$(".navbar-default .container-fluid").css("top","0");
	}
});

$(document).ready(function() {
	if(!(window.__wlDisableRealityCheckPolling === true)){
		setInterval(function(){
			realityCheck();
		},1000);
	}
});

function realityCheck(){
	$.post("/resources/php_functions/reality-check-timer.php", {
		autoRealityCheck: true
	},
	function(data, status){
		if(data !== ""){
			let startTimeOnSite = $(".timeOnSiteCounter").data('drawdate');
			$("#realityCheckPopup, #overlay").show();
			$("#realityCheckTime").html(get_formatted_time_string(startTimeOnSite))
		}
	});
}

$("#realityCheckForm").click(function(){
	$.post("/resources/php_functions/reality-check-timer.php", {
		confirmedRealityCheck: true
	},
	function(data, status){
		$("#realityCheckPopup").hide();
		if($(".alertWindow,.formPopup,.infoWindow,.mobile-nav-dropdown").is(":visible")){
		} else {
			$("#overlay").hide();
		}
	});
});

function get_formatted_time_string(total_seconds) {
	var hours = Math.floor(total_seconds / 3600);
	total_seconds = total_seconds % 3600;

	var minutes = Math.floor(total_seconds / 60);
	total_seconds = total_seconds % 60;
	hoursText = hours + " Hour and ";
	if(hours > 1){
		hoursText = hours + " Hours and ";
	} else if(hours == 0){
		hoursText = "";
	}

	minuteText = minutes + " Minutes";
	var currentTimeString = hoursText + minuteText;

	return currentTimeString;
}

if(window.location.href.indexOf("French-Lotto") > -1) {
	if(window.location.href.indexOf("10-to-win") > -1){
		$(".promotionsNav,.mobile-nav-promo-10towin-1").addClass('active-nav');
	} else if(window.location.href.indexOf("Lucky-5") > -1){
		$(".promotionsNav,.mobile-nav-promo-lucky5-1").addClass('active-nav');
	} else {
		$(".singleLotteryNav,.mobile-nav-lotto-1").addClass('active-nav');
	}
} else if(window.location.href.indexOf("EuroMillions") > -1) {
	if(window.location.href.indexOf("Lucky-5") > -1){
		$(".promotionsNav,.mobile-nav-promo-lucky5-4").addClass('active-nav');
	} else {
		$(".singleLotteryNav,.mobile-nav-lotto-4").addClass('active-nav');
	}
} else if(window.location.href.indexOf("Irish-Lotto") > -1) {
	if(window.location.href.indexOf("Lucky-5") > -1){
		$(".promotionsNav,.mobile-nav-promo-lucky5-3").addClass('active-nav');
	} else {
		$(".singleLotteryNav,.mobile-nav-lotto-3").addClass('active-nav');
	}
} else if(window.location.href.indexOf("Oz-Lotto") > -1) {
	if(window.location.href.indexOf("Lucky-5") > -1){
		$(".promotionsNav,.mobile-nav-promo-lucky5-2").addClass('active-nav');
	} else {
		$(".singleLotteryNav,.mobile-nav-lotto-2").addClass('active-nav');
	}
} else if(window.location.href.indexOf("promotions") > -1) {
	if(window.location.href.indexOf("specialoffer1") > -1) {
	} else {
		$(".promotionsNav").addClass('active-nav');
	}
} else if(window.location.href.indexOf("Australian-Lotto-645") > -1) {
	$(".singleLotteryNav,.mobile-nav-lotto-7").addClass('active-nav');
} else if(window.location.href.indexOf("American-Mega-Millions") > -1) {
	$(".singleLotteryNav,.mobile-nav-lotto-9").addClass('active-nav');
} else if(window.location.href.indexOf("American-Powerball") > -1) {
	$(".singleLotteryNav,.mobile-nav-lotto-8").addClass('active-nav');
} else if(window.location.href.indexOf("Eurojackpot") > -1) {
	$(".singleLotteryNav,.mobile-nav-lotto-11").addClass('active-nav');
} else if(window.location.href.indexOf("Australian-Superdraw") > -1) {
	$(".singleLotteryNav,.mobile-nav-lotto-13").addClass('active-nav');
} else if(window.location.href.indexOf("SuperEnalotto") > -1) {
	$(".singleLotteryNav,.mobile-nav-lotto-14").addClass('active-nav');
} else if(window.location.href.indexOf("contact-us") > -1) {
	if($("#contactUs-recaptcha").length) {
		loadRecaptcha();
	}
	$(".contactUsNav").addClass('active-nav');
} else if(window.location.href.indexOf("account") > -1) {
	$(".accountNav").addClass('active-nav');
} else if(window.location.href.indexOf("french-lotto-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-1").addClass('active-nav');
} else if(window.location.href.indexOf("irish-lotto-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-3").addClass('active-nav');
} else if(window.location.href.indexOf("oz-lotto-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-2").addClass('active-nav');
} else if(window.location.href.indexOf("euromillions-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-4").addClass('active-nav');
} else if(window.location.href.indexOf("australian-lotto-645-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-7").addClass('active-nav');
} else if(window.location.href.indexOf("spanish-lotto-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-5").addClass('active-nav');
} else if(window.location.href.indexOf("german-lotto-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-6").addClass('active-nav');
} else if(window.location.href.indexOf("american-powerball-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-8").addClass('active-nav');
} else if(window.location.href.indexOf("american-mega-millions-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-9").addClass('active-nav');
} else if(window.location.href.indexOf("australian-powerball-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-10").addClass('active-nav');
} else if(window.location.href.indexOf("eurojackpot-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-11").addClass('active-nav');
} else if(window.location.href.indexOf("superenalotto-winning-numbers") > -1) {
	$(".lotteryResultsNav,.mobile-results-nav-lotto-14").addClass('active-nav');
} else if(window.location.href.indexOf("lottery-results") > -1) {
	$(".lotteryResultsNav").addClass('active-nav');
}

$(".showTopUpForm").on('click', function () {
	window.location.replace('/wallet/add-funds');
});

$('.showCVVInfo').on('click', function () {
	$(".cvvInfoWindow").show();
	if($(".infoWindow .infoWindowHeader").css("display") == "block"){
		$(".topUpPaymentOverlay").show().css("z-index","5");
	}
});

$('#showSyndicateInfo').on('click', function () {
	$("#syndicateInfoWindow").show();
	if($("#syndicateInfoWindow .infoWindowHeader").is(":visible")){
		$("#overlay").show();
	}
});

$('#showSubscriptionInfo').on('click', function () {
	$("#subscriptionInfoWindow").show();
	if($(".infoWindow .infoWindowHeader").css("display") == "block"){
		$("#overlay").show();
	}
});

$('#showSupSyndicateInfo').on('click', function () {
	$("#superSyndicateInfoWindow").show();
});

$('#showRegSyndicateInfo').on('click', function () {
	$("#regSyndicateInfoWindow").show();
});

$('.regularSyndicateLines').on('click', function () {
	$("#regSyndicateLinesWindow").show();
});

$('.viewSyndicateLines').on('click', function (e) {
	let idName = e.target.id;
	$('.syndicateLinesPopup.'+idName).show();
});

$('.showAgeVerificationForm').on('click', function () {
	$("#overlay,#uploadAgeVerificationDocsForm").show();
	$("#verifyIdentityPopUp").hide();
});

$('.account_disabled').on('click', function () {
	$("#overlay,#disabledAccount").show();
});

$(document).on('mouseout','.infoButton',function(){
	$(".infoWindow").hide();
});

$(".registrationFormLink").click(function() {
	$("#registerEmail").focus();
	var registerDOBSession = $("#registerDOBSession").val();
	if(registerDOBSession != ''){
		setSavedDOB(registerDOBSession);
	}
});

$(".forgotPasswordLink").click(function() {
	loadRecaptcha();
	$("#overlay,#forgotPasswordFormPopUp").show();
	$("#forgotPasswordEmail").focus();
});

$(".isProxy").click(function() {
	$("#isProxyPopUp,#overlay").show();
});

$(".blockedCountryNoBets").click(function() {
	$("#blockCountryFromRegister,#blockCountryFromAddFunds").hide();
	$("#blockCountryPopUp,#overlay,#blockCountryFromBets").show();
});

$(".isSanctionedCountry").click(function() {
	$("#blockCountryFromBets,#blockCountryFromAddFunds").hide();
	$("#blockCountryPopUp,#overlay,#blockCountryFromRegister").show();
});
		
function showSignInPassword() {
	var x = document.getElementById("signInPassword");
	var y = document.getElementById("signInPasswordImage");
	if (x.type === "password") {
		x.type = "text";
		y.src = "https://lottoexpress.com/resources/images/eye___u26.svg";
		y.setAttribute("class", "showPassword");
	} else {
		x.type = "password";
		y.src = "https://lottoexpress.com/resources/images/eye_u25.svg";
		y.setAttribute("class", "hidePassword");
	}
}

$('a').on("click", function(e) {
	if(window.location.href.indexOf("register") > -1) { 	
		let giveWarning = false;
		$('.registerInput').each(function(i){
			if($( this ).val() !== ''){
				giveWarning = true;
				return false;
			}
		});
		if(giveWarning == true){
			e.preventDefault();
			$('#overlay').show();
			let clickedLink = $(this).attr('href');
			dialog(yesCallback,clickedLink);
		}
	}
});

function yesCallback(url){
	window.location.href = url;
}

function dialog(yesCallback, url) {
    var dialog = $('#warningUnsavedContentPopup').dialog().show();

    $('#btnYes').click(function() {
        yesCallback(url);
    });
    $('#btnNo').click(function() {
		$('#overlay').hide();
		dialog.dialog('close');
    });
}

$( document ).ready(function() {
	$('#signInForm').each(function() {
		$(this).validate({
			rules:{
				signInEmail: { 
					required: true
				}, 
				signInPassword: { 
					required: true
				} 
			},
			messages: {
				signInEmail: "Required format: xxxx@xxx.xxx",
				signInPassword:	"Required Field"
			}
		});
	});
});

$('#signInForm').submit(function () {
	if($(this).valid()) {
		$("#signInSubmit").attr("disabled", "disabled");
		$(".regSigninError,.successCopy").hide();
		$("#initializingAccount").show();
		$('.loader').show();
	}
});
		
$("#registerDOB").dateDropdowns({
	defaultDate: null,
	defaultDateFormat: "yyyy-mm-dd",
	submitFormat: "yyyy-mm-dd",
	minAge: 18,
	submitFieldName: "registerDOB",
	daySuffixes: false,
	required:true
});

function showRegistationPassword() {
	var x = document.getElementById("registerPassword");
	var y = document.getElementById("registerPasswordImage");
	if (x.type === "password") {
		x.type = "text";
		y.src = "https://lottoexpress.com/resources/images/eye___u26.svg";
		y.setAttribute("class", "showPassword");
	} else {
		x.type = "password";
		y.src = "https://lottoexpress.com/resources/images/eye_u25.svg";
		y.setAttribute("class", "hidePassword");
	}
}

$(function() {
	$('#registerForm').validate({
		rules:{
			registerEmail: { required: true }, 
			registerPassword: {	required: true, passwordCheckRegister: true, checkRegisterUsernameNotPassword:true },
			registerFirstName: { required: true },
			registerLastName: { required: true },
			registerPhone: { required: true },
			registerCountry: { required: true },
			confirmTermsConditions: { required: true }
		},
		messages: {
			registerEmail: "Required format: xxxx@xxx.xxx",
			registerPassword: {
                required: "Required Field",
                passwordCheckRegister: "",
				checkRegisterUsernameNotPassword: "Password cannot be your email"
            },
			confirmTermsConditions: ""
		}
	});
	$.validator.addMethod("passwordCheckRegister", function(value,element) {
		return /^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@#$%^&*-/_!+=|:',.?`~";(){}[\]\\])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{8,}$/.test(value)
	});
	
	$.validator.addMethod("checkRegisterUsernameNotPassword", function(value,element) {
		var username = $("#registerEmail").val().trim().toLowerCase();
		var password = $("#registerPassword").val().trim().toLowerCase();
		if(username == password) return false;
		return true;
	});
});

$('#registerForm').submit(function () {
	let countryInfo = iti.getSelectedCountryData();
	let dialCode = countryInfo['dialCode'];
	if(typeof dialCode !== 'undefined'){
		$("input[name='registerDialCode']").val(dialCode);
	}
	if ($('input[name="confirmTermsConditions"]', this).is(':checked')) {	
		if(($(this).valid()) && (recaptcha == true)) {
			$("#registerSubmit").attr("disabled", "disabled");
			$('.loader').show();
		} else {
			if(recaptcha != true){
				$('#recaptcha iframe').addClass('recaptchaError');
			}
			return false;
			
		}
	} else {
		$("#confirmTermsConditionsCheckbox").addClass("redText")
	}
});

$("#registerPassword").on('click', function(){
	$("#registerPasswordValidator").show();
});

$("#registerPassword").keyup(function(){
	var registerPasswordCheck = $("input[name=registerPassword]").val();
	if(registerPasswordCheck.match(/^[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{8,}$/)){
		$("#registerPasswordLength").css("color","#59C203");
	} else {
		$("#registerPasswordLength").css("color","#DE5353");
	}
	if(registerPasswordCheck.match(/^(?=.*\d)[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
		$("#registerPasswordDigit").css("color","#59C203");
	} else {
		$("#registerPasswordDigit").css("color","#DE5353");
	}
	if(registerPasswordCheck.match(/^(?=.*[a-z])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
		$("#registerPasswordLower").css("color","#59C203");
	} else {
		$("#registerPasswordLower").css("color","#DE5353");
	}
	if(registerPasswordCheck.match(/^(?=.*[A-Z])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
		$("#registerPasswordUpper").css("color","#59C203");
	} else {
		$("#registerPasswordUpper").css("color","#DE5353");
	}
	if(registerPasswordCheck.match(/^(?=.*[@#$%^&*-/_!+=|:',.?`~";(){}[\]\\])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
		$("#registerPasswordSpecial").css("color","#59C203");
	} else {
		$("#registerPasswordSpecial").css("color","#DE5353");
	}
	
	
	if(registerPasswordCheck.match(/^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@#$%^&*-/_!+=|:',.?`~";(){}[\]\\])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{8,}$/)){
		$("#registerPasswordValidator").hide();
	} else {
		$("#registerPasswordValidator").show();
	}
});
		
$(".date-dropdowns select").change(function(){
	dobDateError();
});

$("#registerSubmit").click(function(){
	dobDateError();
});

function dobDateError(){
	dobLabelArray = ["label[for='registerDOB_[day]']","label[for='registerDOB_[month]']","label[for='registerDOB_[year]']"];
	dobArray = [".day",".month",".year"];
	dobNotSelectedArray = [];
	dobCount = 0;
	setTimeout(function(){
		for(i=0;i<=2;i++){
			var selectOptionValue = ($(dobArray[i]+" option:selected").val());
			if(($(dobArray[i]).hasClass("error")) && (selectOptionValue === "")){
				dobNotSelectedArray.push(dobLabelArray[i]);
				dobCount++
			}
			if(dobCount > 1){
				$(dobLabelArray[i] + ".error").css("display","none");
			}
		}
		if(dobCount > 0){
			$(dobNotSelectedArray[0] + ".error").css("display","inline-block");
		} else {
			$(dobNotSelectedArray[0] + ".error").css("display","none");
		}
	},100);
}

function setSavedDOB(DOB){
	var savedDOBSplit = DOB.split("-");
	$("#registerForm .year").val(savedDOBSplit[0]);
	$("#registerForm .month").val(savedDOBSplit[1]);
	$("#registerForm .day").val(savedDOBSplit[2]);
	$("#registerDOB").val(DOB);
}

$( document ).ready(function() {
	$('#forgotPasswordForm').each(function() {
		$(this).validate({
			rules:{
				forgotPasswordEmail: { 
					required: true
				}
			},
			messages: {
				forgotPasswordEmail: "Required format: xxxx@xxx.xxx"
			}
		});
	});
});

$('#forgotPasswordForm').submit(function () {
	if(($(this).valid()) && (fpRecaptch == true)) {
		$("#forgotPasswordSubmit").attr("disabled", "disabled");
		$('.loader').show();
	} else {
		if(fpRecaptch != true){
			$('#fp-recaptcha iframe').addClass('recaptchaError');
		}
		return false;
	}
});

function showSetPassword() {
	var x = document.getElementById("setPassword");
	var y = document.getElementById("setPasswordImage");
	if (x.type === "password") {
		x.type = "text";
		y.src = "https://lottoexpress.com/resources/images/eye___u26.svg";
		y.setAttribute("class", "showPassword");
	} else {
		x.type = "password";
		y.src = "https://lottoexpress.com/resources/images/eye_u25.svg";
		y.setAttribute("class", "hidePassword");
	}
}

$( document ).ready(function() {
	$('#setPasswordForm').each(function() {
		$(this).validate({
			rules:{
				setPassword: {	required: true, setPasswordCheck: true, checkUsernameNotTempPassword:true },
				setPasswordTermsConditions: { required: true }
			},
			messages: {
				setPassword: {
					required: "Required Field",
					setPasswordCheck: "",
					checkUsernameNotTempPassword: "Password cannot be your email"
				},
				setPasswordTermsConditions: ""
			}
		});
	});
	$.validator.addMethod("setPasswordCheck", function(value,element) {
		return /^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@#$%^&*-/_!+=|:',.?`~";(){}[\]\\])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{8,}$/.test(value)
	});
	
	$.validator.addMethod("checkUsernameNotTempPassword", function(value,element) {
		return true;
	});
});
	
$('#setPasswordForm').submit(function () {	
	if(!$('input[name="setPasswordTermsConditions"]', this).is(':checked')){	
		$("#setPasswordTermsConditions").addClass("redText");
		$("#setPasswordTermsConditions .redesignCheckmark").css("border-color","red");
		return false;
	}
	if($(this).valid()) {
		$("#setPasswordSubmit").attr("disabled", "disabled");
		$('.loader').show();
	}
});

$("#setPassword").keyup(function(){
	var setPasswordCheck = $("input[name=setPassword]").val();
	checkPasswordValidity(setPasswordCheck);
});

function showNewPassword() {
	var x = document.getElementById("newPassword");
	var y = document.getElementById("newPasswordImage");
	if (x.type === "password") {
		x.type = "text";
		y.src = "https://lottoexpress.com/resources/images/eye___u26.svg";
		y.setAttribute("class", "showPassword");
	} else {
		x.type = "password";
		y.src = "https://lottoexpress.com/resources/images/eye_u25.svg";
		y.setAttribute("class", "hidePassword");
	}
}

$(function() {
	$('#changePasswordForm').validate({
		rules:{
			newPassword: { required: true, passwordCheck: true, checkEmailNotPassword: true },
			confirmPassword: { required: true, confirmPasswordMatch: true },
			setPasswordTermsConditions: { required: true }
		},
		messages: {
			newPassword: {
                required: "",
				passwordCheck: "",
				checkEmailNotPassword: "Password cannot be your email"
            },
			confirmPassword: {
                required: "",
				confirmPasswordMatch: "Passwords do not match"
            },
			setPasswordTermsConditions: ""
		}
	});
	
	$.validator.addMethod("passwordCheck", function(value,element) {
		return /^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@#$%^&*-/_!+=|:',.?`~";(){}[\]\\])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{8,}$/.test(value)
	});
	
	$.validator.addMethod("checkEmailNotPassword", function(value,element) {
		var username = $("input[name=newPasswordEmail]").val().trim().toLowerCase();
		var password = $("#newPassword").val().trim().toLowerCase();
		console.log(username+"=="+password);
		if(username == password) return false;
		return true;
	});
	
	$.validator.addMethod("confirmPasswordMatch", function(value,element) {
		var password = $("#newPassword").val();
		var confirmPassword = $("#confirmPassword").val();
		if(password == confirmPassword) return true;
		return false;
	});
});

$('#changePasswordForm').submit(function () {
	if(!$('input[name="newPasswordTermsConditions"]', this).is(':checked')){	
		$("#newPasswordTermsConditions").addClass("redText");
		$("#newPasswordTermsConditions .redesignCheckmark").css("border-color","red");
		return false;
	}
	if($(this).valid()){
		$('.loader').show();
		return true;
	} else {
		return false;
	}
});

$("#newPassword").keyup(function(){
	var setPasswordCheck = $("input[name=newPassword]").val();
	checkPasswordValidity(setPasswordCheck);
});

function checkPasswordValidity(setPasswordCheck){
	if(setPasswordCheck.match(/^[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{8,}$/)){
		$(".setPasswordLength").css("color","#59C203");
	} else {
		$(".setPasswordLength").css("color","#DE5353");
	}
	if(setPasswordCheck.match(/^(?=.*\d)[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
		$(".setPasswordDigit").css("color","#59C203");
	} else {
		$(".setPasswordDigit").css("color","#DE5353");
	}
	if(setPasswordCheck.match(/^(?=.*[a-z])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
		$(".setPasswordLower").css("color","#59C203");
	} else {
		$(".setPasswordLower").css("color","#DE5353");
	}
	if(setPasswordCheck.match(/^(?=.*[A-Z])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
		$(".setPasswordUpper").css("color","#59C203");
	} else {
		$(".setPasswordUpper").css("color","#DE5353");
	}
	if(setPasswordCheck.match(/^(?=.*[@#$%^&*-/_!+=|:',.?`~";(){}[\]\\])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{1,}$/)){
		$(".setPasswordSpecial").css("color","#59C203");
	} else {
		$(".setPasswordSpecial").css("color","#DE5353");
	}
	
	if(setPasswordCheck.match(/^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@#$%^&*-/_!+=|:',.?`~";(){}[\]\\])[0-9a-zA-Z@#$%^&*-/_!+=|:',.?`~";(){}[\]\\]{8,}$/)){
		$("#registerPasswordValidator,#newPasswordValidator").hide();
	} else {
		$("#registerPasswordValidator,#newPasswordValidator").show();
	}
}

$("#setPasswordExpiredButton").on('click',function(){
	loadRecaptcha();
	$('#setPasswordExpiredPopUp').hide();
	$('#forgotPasswordFormPopUp').show();
});

$('.resendVerifyEmail').submit(function(e){
	$('.loader').show();
	e.preventDefault();
	$('input[type="submit"').attr("disabled", true);
	$.post("/resources/php_functions/verify-email-resend.php",{
		resendVerifyEmail: true
	},
	function(data,status){
		$("#verifyEmailPendingPopUp,#verifyEmailPopUp,#emailVerifiedFailed,#emailVerifiedExpired").hide();
		$('input[type="submit"').attr("disabled", false);
		$(".loader").hide();
		console.log(data);
		if(data == "success"){
			$("#verifyEmailPopUp").show();
		} else {
			$("#emailVerifiedFailed").show();
		}
	});
});

if(window.location.href.indexOf("status=sign-in-error") > -1) {
	$("#signInFailed").show();
	cleanURL();
} else if(window.location.href.indexOf("status=set-password-form") > -1) {
	$("#setPasswordFormPopUp,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=set-password-success") > -1) {
	$("#setPasswordSuccess").show();
	cleanURL();
} else if(window.location.href.indexOf("status=register-error") > -1) {
	$("#registrationFailed,.registerConfirmSection").show();
	var registerDOBSession = $("#registerDOBSession").val();
	if(registerDOBSession != ''){
		setSavedDOB(registerDOBSession);
	}
	if(window.location.href.indexOf("promotions/specialoffer") > -1){
		$("#registerFormTitle").html("Enter your Details");
	}
	cleanURL();
}  else if(window.location.href.indexOf("status=register-form") > -1) {
	$('.registerConfirmSection').show();
	window.location.replace("/register#status=register-form");
	if(window.location.href.indexOf("promotions/specialoffer") > -1){
		$("#registerFormTitle").html("Enter your Details");
	}
	cleanURL();
} else if(window.location.href.indexOf("status=forgot-password-error") > -1) {
	loadRecaptcha();
	$("#forgotPasswordFormPopUp,#overlay,#forgotPasswordFailed").show();
	cleanURL();
} else if(window.location.href.indexOf("status=reset-password") > -1) {
	$("#forgotPasswordFormPopUp,#overlay,#forgotPasswordSuccess").show();
	cleanURL();
} else if(window.location.href.indexOf("status=set-password-email-sent") > -1) {
	$("#setPasswordEmailPopUp,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=force-logout") > -1) {
	$("#sessionExpiredPopUp,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=add-cc-for-subscription") > -1) {
	if(window.location.href.indexOf("account") > -1) {
		showAccountOrdersPage();
	}
	$("#paymentForSubscriptionFormPopUp,#overlay").show();
	if(!$("#liveCCForSubscriptionForm").length == 0){
		isCitySet("liveCCForSubscriptionAddressCity","liveCCForSubscriptionPositionOneCity","liveCCForSubscriptionCountry");
	}
	cleanURL();
} else if(window.location.href.indexOf("status=show-error") > -1) {
	$("#fatalErrorMessage,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=verify-identity") > -1) {
	$("#verifyIdentityPopUp,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=on-gameStop-list") > -1) {
	$("#onGamStopPopup,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=account-inactive") > -1) {
	$("#accountInactivePopup,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=account-on-hold") > -1) {
	$("#accountOnHoldPopup,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=wallet-bet-limit-exceeded") > -1) {
	if(window.location.href.indexOf("account") > -1) {
		showAccountOrdersPage();
	}
	$("#overDailyLimitsPopup,#overlay,#overBetLimit").show();
	cleanURL();
} else if(window.location.href.indexOf("status=over-bet-deposit-limit") > -1) {
	$("#overDailyLimitsPopup,#overlay,#overBetDailyDepositLimit").show();
	cleanURL();
} else if(window.location.href.indexOf("status=over-deposit-limit") > -1) {
	$("#overDailyLimitsPopup,#overlay,#overDepositLimit").show();
	cleanURL();
} else if(window.location.href.indexOf("status=exceeded-limits") > -1) {
	$("#overDailyLimitsPopup,#overlay,#overLimits").show();
	cleanURL();
} else if(window.location.href.indexOf("status=error-with-message") > -1) {
	$("#errorWithMessage,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=upload-docs-success") > -1) {
	$("#documentsUploadSuccess,#overlay").show();
	$(".accountUpdateFailCopy").hide();
	cleanURL();
} else if(window.location.href.indexOf("status=upload-docs-failed") > -1) {
	$("#documentsUploadSuccess,#overlay").show();
	$(".accountUpdateSuccess").hide();
	cleanURL();
} else if(window.location.href.indexOf("status=proxy-detected") > -1) {
	$("#isProxyPopUp,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=blocked-country") > -1) {
	$("#blockCountryPopUp,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=disabled-account") > -1) {
	$("#disabledAccount,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=locked-account") > -1) {
	$("#acctLockedPopUp,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=closed-account") > -1) { 
	$("#acctClosedPopUp,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=verify-email-pending") > -1) {
	$("#verifyEmailPendingPopUp,#overlay").show();	
	cleanURL();
} else if(window.location.href.indexOf("status=verify-email") > -1) {
	$("#verifyEmailPopUp,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=verified-email-success") > -1) {
	$("#verifiedEmailSuccess").show();
	cleanURL();
} else if(window.location.href.indexOf("status=verified-email-expired") > -1) {
	$("#emailVerifiedExpired,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=verified-email-failed") > -1) {
	$("#emailVerifiedFailed,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=limits-error") > -1) {
	$("#setLimitFailedPopUp,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=already-logged-in") > -1) {
	$("#alreadyLoggedInForm,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=payment-3ds-form") > -1) {
	$('.loader').hide();
	$("#payment3DSForm,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("status=gpay-payment-form") > -1) {
	$('.loader').hide();
	$("#gpayPaymentForm,#overlay").show();
	cleanURL();
} else if(window.location.href.indexOf("?email-link-to-winnings") > -1) {
	if($("#realityCheckPopup").length > 0) {
		document.location = "/account#winnings";
	} else {
		document.location = "/login";
	}
	cleanGETURL();
} else if(window.location.href.indexOf("?emailLinkTo=order-history-table") > -1) {
	if($("#realityCheckPopup").length > 0) { 
		document.location = "/account#showOrderId";
	} else {
		document.location = "/login";
	}
	cleanGETURL();
} else if(window.location.href.indexOf("?emailLinkTo=account-profile") > -1) {
	if($("#realityCheckPopup").length > 0) {
		document.location = "/account#showAccountProfile";
	} else {
		document.location = "/login";
	}
	cleanGETURL();
}

function showAccountOrdersPage(){
	$("#myDetailsSection,#lotteryWalletSection,#notificationSection").hide();
	$("#myDetailsTab,#notificationTab,#lotteryWalletTab").removeClass('accountTabActive');
	$("#lotteryOrderSection").show();
	$("#lotteryOrderTab").addClass('accountTabActive');
	// By id, not by class. Both order panels carry this class, so selecting on
	// it opened the imported AS400 history alongside the real one.
	$("#orderHistoryDropDown").addClass('active');
}

function cleanURL(){
	var uri = window.location.toString();
	var clean_uri = uri.substring(0, uri.indexOf("#"));
	window.history.pushState(null,null,clean_uri);
}

function cleanGETURL(){
	var uri = window.location.toString();
	var clean_uri = uri.substring(0, uri.indexOf("?"));
	window.history.pushState(null,null,clean_uri);
}

$('input[name="uploadIDButton"]').prop('disabled', true);	
$('#uploadDL').change(function() {
	var filename = $(this).val();
	if(filename != ""){
		var ext = $('#uploadDL').val().split('.').pop().toLowerCase();
		if($.inArray(ext, ['png','jpg','jpeg']) == -1) {
			alert('We only accept .png, .jpg, or .jpeg file extensions.');
		} else if(this.files[0].size / 1024 > 10000){
			alert("Your file is too large. It must be Max size 10MB");
		} else {
			var lastIndex = filename.lastIndexOf("\\");
			if (lastIndex >= 0) {
				filename = filename.substring(lastIndex + 1);
			}
			$("label[for=uploadDL]").html("Upload Drivers License");
			$("#uploadDLFilenameImg").show();
			$('#uploadDLFilename').html(filename);
			$('#dlExpiryDate').css({"opacity":"1","pointer-events":"auto"});
			submitIdentityDocuments();
		}
	} else {
		$("label[for=uploadDL]").html("Upload Drivers License");
		$("#uploadDLFilenameImg").hide();
		$('#uploadDLFilename').html("JPG or PNG. Max size 10MB.");
		$('#dlExpiryDate').css({"opacity":"0.2","pointer-events":"none"});
		submitIdentityDocuments();
	}
});


$("#uploadDLExpiry").change(function(){
	if($("#uploadDLExpiry").val() != ""){
		submitIdentityDocuments();
	}
});
	
$('#uploadPassport').change(function() {
	var filename = $(this).val();
	if(filename != ""){
		var ext = $('#uploadPassport').val().split('.').pop().toLowerCase();
		if($.inArray(ext, ['png','jpg','jpeg']) == -1) {
			alert('We only accept .png, .jpg, or .jpeg file extensions.');
		} else if(this.files[0].size / 1024 > 10000){
			alert("Your file is too large. It must be Max size 10MB");
		} else {
			var lastIndex = filename.lastIndexOf("\\");
			if (lastIndex >= 0) {
				filename = filename.substring(lastIndex + 1);
			}
			$("label[for=uploadPassport]").html("Upload Passport");
			$("#uploadPassportFilenameImg").show();
			$('#uploadPassportFilename').html(filename);
			$('#passportExpiryDate').css({"opacity":"1","pointer-events":"auto"});
			uploadPassportBill();
			submitIdentityDocuments();
		}
	} else {
		$("label[for=uploadPassport]").html("Upload Passport");
		$("#uploadPassportFilenameImg").hide();
		$('#uploadPassportFilename').html("JPG or PNG. Max size 10MB.");
		$('#passportExpiryDate').css({"opacity":"0.2","pointer-events":"none"});
		submitIdentityDocuments();
	}
});

$("#uploadPassportExpiry").change(function(){
	if($("#uploadPassportExpiry").val() != ""){
		submitIdentityDocuments();
	}
});
		
$('#uploadBill').change(function() {
	var filename = $(this).val();
	if(filename != ""){
		var ext = $('#uploadBill').val().split('.').pop().toLowerCase();
		if($.inArray(ext, ['png','jpg','jpeg']) == -1) {
			alert('We only accept .png, .jpg, or .jpeg file extensions.');
		} else if(this.files[0].size / 1024 > 10000){
			alert("Your file is too large. It must be Max size 10MB");
		} else {
			var lastIndex = filename.lastIndexOf("\\");
			if (lastIndex >= 0) {
				filename = filename.substring(lastIndex + 1);
			}
			$("label[for=uploadBill]").html("Upload Utility Bill");
			$("#uploadBillFilenameImg").show();
			$('#uploadBillFilename').html(filename);
			uploadPassportBill();
		}
	} else {
		$("label[for=uploadBill]").html("Upload Utility Bill");
		$("#uploadBillFilenameImg").hide();
		$('#uploadBillFilename').html("JPG or PNG. Max size 10MB.");
		submitIdentityDocuments();
	}
});
		
function uploadPassportBill(){
	var passportFileName = $("#uploadPassport").val();
	var billFileName = $("#uploadBill").val();
	if(passportFileName && billFileName){
		submitIdentityDocuments();
	}
}

var dlExpiryCurrentYear = new Date().getFullYear();
var dlExpiryMaxYear = dlExpiryCurrentYear + 20;
$("#uploadDLExpiry").dateDropdowns({
	defaultDate: null,
	defaultDateFormat: "yyyy-mm-dd",
	submitFormat: "yyyy-mm-dd",
	submitFieldName: "uploadDLExpiry",
	displayFormat: "dmy",
	minYear:dlExpiryCurrentYear,
	maxYear:dlExpiryMaxYear,
	daySuffixes: false
});

$("#uploadPassportExpiry").dateDropdowns({
	defaultDate: null,
	defaultDateFormat: "yyyy-mm-dd",
	submitFormat: "yyyy-mm-dd",
	submitFieldName: "uploadPassportExpiry",
	displayFormat: "dmy",
	minYear:dlExpiryCurrentYear,
	maxYear:dlExpiryMaxYear,
	daySuffixes: false
});

$("#uploadIDButton").click(function(){
	if(submitIdentityDocuments() == true){
		if($(this).valid()) {
			$('.loader').show();
		}
		return true;
	} else {
		alert("Please fill in required fields");
		return false;
	}
});

function submitIdentityDocuments(){
	if($('#uploadDL').val() != ""){
		if($("#uploadDLExpiry").val() != ""){
			if($('#uploadPassport').val() == ""){
				solidUploadDocumentButton();
				return true;
			} else {
				if($("#uploadPassportExpiry").val() != ""){
					solidUploadDocumentButton();
					return true;
				} else {
					opacityUploadDocumentButton();
					return false;
				}
			}
		} else {
			opacityUploadDocumentButton();
			return false;
		}
	}
	if($('#uploadPassport').val() != "" && $('#uploadBill').val() != "" ){
		if($("#uploadPassportExpiry").val() != ""){
			if($('#uploadDL').val() == ""){
				solidUploadDocumentButton();
				return true;
			} else { 
				if($("#uploadDLExpiry").val() != ""){
					solidUploadDocumentButton();
					return true;
				} else {
					opacityUploadDocumentButton();
					return false;
				}
			}
		} else {
			opacityUploadDocumentButton();
			return false;
		}
	} 
	opacityUploadDocumentButton();
	return false;
}

function solidUploadDocumentButton(){
	$('input[name="uploadIDButton"]').prop('disabled', false);
	$("#uploadIDButton").removeClass("accountSubmitButtonInactive");
}

function opacityUploadDocumentButton(){
	$('input[name="uploadIDButton"]').prop('disabled', true);
	$("#uploadIDButton").addClass("accountSubmitButtonInactive");
}

$("#singlePlayBetForm").submit(function(){
	var countDrawDaysChecked = $("#lottoDrawDays input[type='checkbox']:checked").length;
	if(($(this).valid()) && (countDrawDaysChecked > 0)) {
		$("#placeBetButton").attr("disabled", "disabled");
		$('.loader').show();
	} else {
		if(countDrawDaysChecked == 0){
			alert("You must select a draw day to continue with your play");
		}
		return false;
	}
});

$(".syndicateForm").submit(function(){
	if($(this).valid()){
		$("#placeBetButton").attr("disabled", "disabled");
		$('.loader').show();
	} else {
		return false;
	}
});

$(".multiShareSyndicateForm").submit(function(){
	let shareCount = $(this).find(".shareCount").val();
	$("input[name='shareCount']").val(shareCount);
	if($(this).valid()){
		$("#placeBetButton").attr("disabled", "disabled");
		$('.loader').show();
	} else {
		return false;
	}
});

$("#confirmBetForm").submit(function(){
	$("#confirmBetSubmit").attr("disabled", "disabled");	
	$('.loader').show();
});

$("#confirmSyndicateForm").submit(function(){
	$("#confirmSyndicateSubmit").attr("disabled", "disabled");	
	$('.loader').show();
});

additionalLotteryScroll = 0;
additionalPromoScroll = 0;
let findVisiblePromoWidth = $('.homepageFeaturedPromos').outerWidth();
let findVisibleLotteryWidth = $('.availableLotteries').outerWidth();
let findLotteryContentWidth = $('.lotteryContent').outerWidth();
let scrollPromoAmount = visibleWidth(findVisiblePromoWidth);
let scrollLotteriesAmount = visibleWidth(findVisibleLotteryWidth);

function visibleWidth(findVisibleWidth){
	if(findVisibleWidth > 1000){
		return 450;
	} else if(findVisibleWidth > 800 && findVisibleWidth < 1000){
		return 550;
	} else if(findVisibleWidth > 500 && findVisibleWidth < 800){
		return 450;
	} else if(findVisibleWidth < 360 && findVisibleWidth > 320){
		return 353;
	} else if(findVisibleWidth < 320 && findVisibleWidth > 290){
		return 313;
	} else if(findVisibleWidth < 290){
		return 288;
	} else {
		return 383;
	}
}

$(".lotteriesLeft").click(function(){
	if(additionalLotteryScroll != 0){
		additionalLotteryScroll = additionalLotteryScroll - scrollLotteriesAmount;
		$('.lotteryContent').animate( { left: -additionalLotteryScroll}, 500);
	}
	var scrollWidth = additionalLotteryScroll;
	scrollLeft('lotteriesRight','lotteriesLeft','lotteriesArrowDisabled','availableLotteries',scrollWidth);
});

$(".lotteriesRight").click(function(){
	additionalLotteryScroll = additionalLotteryScroll + scrollLotteriesAmount;
	let scroll = additionalLotteryScroll;
	let hiddenSpace = findLotteryContentWidth - findVisibleLotteryWidth;
	if(additionalLotteryScroll > hiddenSpace){
		scroll = hiddenSpace + 100;
	}
	$('.lotteryContent').animate( { left: -scroll}, 500);
	var scrollWidth = additionalLotteryScroll;
	scrollRight('lotteriesLeft','lotteriesRight','lotteriesArrowDisabled','lotteryContent','availableLotteries',scrollWidth);
});

$(".homepagePromosLeft").click(function(){
	if(additionalPromoScroll != 0){
		additionalPromoScroll = additionalPromoScroll - scrollPromoAmount;
		$('.homepagePromoContent').animate( { left: -additionalPromoScroll}, 500);
	}
	var scrollWidth = additionalPromoScroll;
	scrollLeft('homepagePromosRight','homepagePromosLeft','homepagePromosArrowDisabled','homepageFeaturedPromos',scrollWidth);
});

$(".homepagePromosRight").click(function(){
	additionalPromoScroll = additionalPromoScroll + scrollPromoAmount;
	$('.homepagePromoContent').animate( { left: -additionalPromoScroll}, 500);
	var scrollWidth = additionalPromoScroll;
	scrollRight('homepagePromosLeft','homepagePromosRight','homepagePromosArrowDisabled','homepagePromoContent','homepageFeaturedPromos',scrollWidth);
});

function scrollLeft(rightButtonName,leftButtonName,disabledButtonName,contentName,scrollWidth){
	$("."+rightButtonName+"").removeClass(disabledButtonName);
	var visibleWidth = $('.'+contentName+'').outerWidth();
	var currentPosition = visibleWidth - scrollWidth;
	if(currentPosition == visibleWidth){
		$("."+leftButtonName+"").addClass(disabledButtonName);
	}
}

function scrollRight(leftButtonName,rightButtonName,disabledButtonName,innerContentName,contentName,scrollWidth){
	$('.'+leftButtonName+'').removeClass(disabledButtonName);
	var visibleWidth = $('.'+contentName+'').outerWidth();
	var fullWidth = $('.'+innerContentName+'').outerWidth();
	var currentPosition = scrollWidth + visibleWidth + 5;
	if(currentPosition > fullWidth){
		$('.'+rightButtonName+'').addClass(disabledButtonName);
	}
}

function createResultsNumberPicker(){
	var numberShow ='';
	var index = '';
	var i =1;
	for ( i = 1; i <= settings.PickBallNumber; i++){
		index = settings.stringTags.showNumber +'1_' + i;
		numberShow = '<span class="ticketNumber" id='+ index + '></span>';
		$('#selectedNumbers').append(numberShow);
	}	
	for ( i = 1; i <= settings.MaxBallNumber; i++){
		index = 'ticketNumber_1_' + i;
		numberShow = '<li class="ticketNumber" id='+ index + '  onClick="addNumber(this.id)">' + i +'</li>';
		$('#availableNumbers_1').append(numberShow);
	}
	for ( i = 1; i <= settings.BonusBallNumber; i++){
		index = settings.stringTags.showBonus +'1_' + i;
		numberShow = '<span class="bonusTicketNumber choosenBonus" id ='+ index + '></span>';
		$('#selectedNumbers').append(numberShow);
	}	
	for ( i = 1; i <= settings.MaxBonusBallNumber; i++){
		index = 'bonusTicketNumber_1_' + i;
		numberShow = '<li class="bonusTicketNumber" id='+ index + '  onClick="addNumber(this.id)">' + i +'</li>';
		$('#availableBonusNumbers_1').append(numberShow);
	}
}

$(document).on('click','#resultsCheckNumbersButton',function(){
	var resultNumbersArray = new Array();
	var resultNumbers = new Array();
	var resultBonusNumbers = new Array();
	$('#selectedNumbers .ticketNumber').each(function(){
		resultNumbers.push($(this).html());
	});
	$('#selectedNumbers .bonusTicketNumber ').each(function(){
		resultBonusNumbers.push($(this).html());
	});
	resultNumbersArray.push([resultNumbers,resultBonusNumbers]);
	console.log(resultNumbersArray);
	$.post("/resources/php_functions/get-lottery-results-page-forms.php", {
		resultsCheckNumbers: resultNumbersArray
	},
	function(data, status){
		if(data !== ""){
			console.log(data);
			$("#resultsMatachingNumbers").html("");
			$("#resultsCheckNumberFound").show();
			var res = JSON.parse(data);
			if(res.length > 0){
			for(var x=0;x<=res.length-1;x++){
				$("#resultsMatachingNumbers").append("<ul class='numbersFound' id='numbersFound"+x+"'></ul>");
				if(res[x][0] != ""){
					$("#numbersFound"+x).append("<li class='numberFoundDate'>"+res[x][0]+"</li>");
				}
				if(res[x][1] != ""){
					for(var y=0;y<=res[x][1].length-1;y++){
						$("#numbersFound"+x).append("<li class='resultsBall resultNumber'>"+res[x][1][y]+"</li>");
					}
				}
				if(res[x][2] != ""){
					for(var y=0;y<=res[x][2].length-1;y++){
						$("#numbersFound"+x).append("<li class='resultsBall resultBonusNumber'>"+res[x][2][y]+"</li>");
					}
				}
			}
			} else {
				$("#resultsMatachingNumbers").html("No Matches");
			}
		}
	});
});

$(function() {
	$('#lotteryResultsEmail').validate({
		rules:{
			email_resultsEmail: { required: true }, 
			firstname_resultsEmail: {	required: true },
			lastname_resultsEmail: { required: true }
		},
		messages: {
			email_resultsEmail: "Required format: xxxx@xxx.xxx",
			firstname_resultsEmail: "Required Field",
			lastname_resultsEmail: "Required Field"
		}
	});
});

$('#lotteryResultsEmail').submit(function(e){
	if($(this).valid()){
	$("#resultsFormSubmit").attr("disabled", "disabled");
	$('input[name="hiddenResultsFormField"]').val("resultsFormSubmitted");
	$(".loader").show();
	e.preventDefault();
	var email = $("input[name='email_resultsEmail']").val();
	var firstname = $("input[name='firstname_resultsEmail']").val();
	var lastname = $("input[name='lastname_resultsEmail']").val();
	var pageName = $("input[name='pagename_resultsEmail']").val();
	var hiddenResultsFormField = $("input[name='hiddenResultsFormField']").val();
	var pageURL = window.location.href;
	$.post("/resources/php_functions/hubspot-results-email-signup.php",{
		email: email,
		firstname: firstname,
		lastname: lastname,
		pageName: pageName,
		pageURL: pageURL,
		hiddenResultsFormField: hiddenResultsFormField
	},
	function(data,status){
		$(".loader").hide();
		console.log(data);
		if(data.toUpperCase().indexOf("SUCCESS") >= 0){
			$(".accountUpdateFail").hide();
			$("input[name='email_resultsEmail'],input[name='firstname_resultsEmail'],input[name='lastname_resultsEmail']").val("");
			$('.accountSuccessMessage').html("Thank you!<br><br>You have been added to our results email list");
			$("#accountUpdatedPopup,.accountUpdateSuccess,#overlay").show();
		} else {
			$(".accountUpdateSuccess").hide();
			$('.accountFailedMessage').html("An Error Occurred<br><br>Sorry, we were unable to add you to our results email list. Please try again for contact customer service");
			$("#accountUpdatedPopup,.accountUpdateFail,#overlay").show();
			$("#resultsFormSubmit").attr("disabled", false);
		}
	});
	} else {
		return false;
	}
});

$(document).on('click','#resultsCheckNumbersButtonMobile',function(){
	var resultNumbersArray = new Array();
	var resultNumbers = new Array();
	var resultBonusNumbers = new Array();
	$('#selectedNumbers .ticketNumber').each(function(){
		resultNumbers.push($(this).html());
	});
	$('#selectedNumbers .bonusTicketNumber ').each(function(){
		resultBonusNumbers.push($(this).html());
	});
	resultNumbersArray.push([resultNumbers,resultBonusNumbers]);
	$.post("/resources/php_functions/get-lottery-results-page-forms.php", {
		resultsCheckNumbers: resultNumbersArray
	},
	function(data, status){
		if(data !== ""){
			$("#resultsMatachingNumbers,#resultNumberChecked").html("");
			$("#resultsCheckNumberContent").hide();
			$("#resultsCheckNumberFound,#resultNumbersChecked,#resultsCheckNumberMobile").show();
			for(var x=0;x<=resultNumbersArray.length-1;x++){
				if(resultNumbersArray[x][0] != ""){
					for(var y=0;y<=resultNumbersArray[x][0].length-1;y++){
						$("#resultNumberChecked").append("<li class='resultNumberChecked'>"+resultNumbersArray[0][0][y]+"</li>");
					}
				}
				if(resultNumbersArray[x][1] != ""){
					for(var z=0;z<=resultNumbersArray[x][1].length-1;z++){
						$("#resultNumberChecked").append("<li class='resultBonusNumberChecked'>"+resultNumbersArray[0][1][z]+"</li>");
					}
				}
			}

			
			
			var res = JSON.parse(data);
			if(res.length > 0){
			for(var x=0;x<=res.length-1;x++){
				$("#resultsMatachingNumbers").append("<ul class='numbersFound' id='numbersFound"+x+"'></ul>");
				if(res[x][0] != ""){
					$("#numbersFound"+x).append("<li class='numberFoundDate'>"+res[x][0]+"</li>");
				}
				if(res[x][1] != ""){
					for(var y=0;y<=res[x][1].length-1;y++){
						$("#numbersFound"+x).append("<li class='resultsBall resultNumber'>"+res[x][1][y]+"</li>");
					}
				}
				if(res[x][2] != ""){
					$("#numbersFound"+x).append("<li class='resultsBall resultBonusNumber'>"+res[x][2]+"</li>");
				}
			}
			} else {
				$("#resultsMatachingNumbers").html("No Matches");
			}
		}
	});
});

$(document).on('change','#selectedResultsDate',function(){
	if(window.__wlUseFlaskResultsPage){
		return;
	}
	var selectedResultsDate = $("#selectedResultsDate").val();
	$.post("/resources/php_functions/get-lottery-results-page-forms.php", {
		selectedResultsDate: selectedResultsDate
	},
	function(data, status){
		if(data !== ""){
			$(".accordion").load(location.href + " .accordionLotteryResults",function(){});
		}
	});
});

function clearCheckNumbersButton(id){
	$('#resultsCheckNumberSection .secondaryFormButton').addClass('disabledState');
	$('#resultsCheckNumberSection .primaryFormButton').addClass('disabledState');
	$("#resultsMatachingNumbers").html("");
	$("#resultsCheckNumberFound").hide();
	for( var j = 0; j < settings.selectedTicketNumbers.length; j++){
        if(id == settings.selectedTicketNumbers[j].index){
            for(var k=0;k < settings.selectedTicketNumbers[j].Numbers.length; k++){
                $("#ticketNumber_"+id+"_"+settings.selectedTicketNumbers[j].Numbers[k]).removeClass("selectedNumber");
            }
            for(var l=0;l < settings.selectedTicketNumbers[j].BonusNumbers.length; l++){
                $("#bonusTicketNumber_"+id+"_"+settings.selectedTicketNumbers[j].BonusNumbers[l]).removeClass("selectedNumber");
            }
            settings.selectedTicketNumbers.splice(j,1); 
        }
    }
	$('.ticketNumber').each(function(){
		settings.completedTicketCount--;
		if($(this).hasClass('selectedNumber')){
			$(this).removeClass('selectedNumber');
		}
	});
	$('.bonusTicketNumber').each(function(){
		if($(this).hasClass('selectedNumber')){
			$(this).removeClass('selectedNumber');
		}
	});
}

$("#resultsCheckNumbersMobile").on("click",function(){
	$("#resultsCheckNumberSection").show();
	$("#resultsCheckNumbersMobile,#checkNumbersWindowShow").hide();
});

$("#resultsCheckMobileClose").on("click",function(){
	$("#resultsCheckNumberSection").hide();
	$("#resultsCheckNumbersMobile").show();
});

$("#editResultsTicket").on("click",function(){
	$("#resultsCheckNumberFound").hide();
	$("#resultsCheckNumberContent").show();
});


function hideCheckNumbersMobile(e){
	if (!e) var e = window.event;
    e.cancelBubble = true;
    if (e.stopPropagation) e.stopPropagation();
	$("#checkNumbersWindowContent").hide();
	$("#checkNumbersWindowShow").show();
	$("#resultsCheckNumbersMobile").animate({left: '100%'});
}

$("#checkNumbersWindowShow").on("click",function(e){
	if (!e) var e = window.event;
    e.cancelBubble = true;
    if (e.stopPropagation) e.stopPropagation();
	$("#resultsCheckNumbersMobile").animate({left: '0'});
	$("#checkNumbersWindowContent").show();
});

$(function() {
	$('#contactUsForm').validate({
		rules:{
			firstname: { required: true }, 
			lastname: {	required: true },
			email: { required: true },
			message: { required: true }
		},
		messages: {
			firstname: "",
			lastname: "",
			email: "Required format: xxxx@xxx.xxx",
			message: ""
		}
	});
});

$('#contactUsForm').submit(function () {
	if(($(this).valid()) && (contactUsRecaptch == true)){
		$("#contactUsFormSubmit").attr("disabled", "disabled");
		$('input[name="hiddenContactUsField"]').val("contactUsFormSubmitted");
		$('.loader').show();
		return true;
	} else {
		if(contactUsRecaptch != true){
			$('#contactUs-recaptcha iframe').addClass('recaptchaError');
		}
		return false;
	}
});

$(".syndicateOptions select").change(function(){
		let val = $(this).val();
		showSyndicateBox(val);
	});
	
function showSyndicateBox(val){
	$('.syndicateBox').hide();
	$('.syndicateBox').each(function(i) {
		let className = $(this).attr('class');
		if(className.indexOf("syndicate2") >= 0){
			$('.'+val).show();
			$('.syndicateOptions select').val(val);
		}
	});
}

function isInViewport(el) {
	const rect = el.getBoundingClientRect();
	return (
		rect.top >= 0 &&
		rect.left >= 0 &&
		rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
		rect.right <= (window.innerWidth || document.documentElement.clientWidth)
	);
}

function isHidden(el) {
	return (el.offsetParent === null)
}

let selectOption = document.getElementById("offerSelector");
if(selectOption != null){
	selectOption.addEventListener("click", function() {
		toggleSyndicateButton();
	});
	
	document.addEventListener('scroll', function () {
		toggleSyndicateButton();
	}, {
		passive: true
	});
}

function toggleSyndicateButton(){
	const button1 = document.querySelector('.syndicate1 .syndicateBetButton'); 
	const button2 = document.querySelector('.syndicate2 .syndicateBetButton');
	let box = (isHidden(button1) == false) ? button1 : button2;
	let currentOffer = (isHidden(button1) == false) ? 'syndicate1' : 'syndicate2';
	const messageText = isInViewport(box) ? false : true;
	const doesElementExist = document.getElementsByClassName('stickeySyndicateButton');
	if ((window.innerHeight + window.scrollY + 10) >= document.body.offsetHeight) {
		var list = document.getElementById(currentOffer);
		var children = document.querySelectorAll('.'+currentOffer+" .stickeySyndicateButton");
		children[0].style.display = 'none';
	} else {
		if(doesElementExist.length > 0){
			if(messageText == true){
				var list = document.getElementById(currentOffer);
				var children = document.querySelectorAll('.'+currentOffer+" .stickeySyndicateButton");
				children[0].style.display = 'block';
			} else {
				var list = document.getElementById(currentOffer);
				var children = document.querySelectorAll('.'+currentOffer+" .stickeySyndicateButton");
				children[0].style.display = 'none';
			}
		}
	}
}

function groupCountPlus(className,inputClass,sharesAvailable,unitPrice){
	var currentShareCount = $(inputClass).val();
	if(currentShareCount < sharesAvailable){
		currentShareCount++;
	}
	var updatedSyndicateInput = setSyndicateStatus(className,currentShareCount,sharesAvailable,unitPrice);
	$(inputClass).val(updatedSyndicateInput);
}

function groupCountMinus(className,inputClass,sharesAvailable,unitPrice){
	var currentShareCount = $(inputClass).val();
	if(currentShareCount != 1){
		currentShareCount--;
	}
	var updatedSyndicateInput = setSyndicateStatus(className,currentShareCount,sharesAvailable,unitPrice);
	$(inputClass).val(updatedSyndicateInput);
}

function setSyndicateStatus(className,syndicateInput,sharesAvailable,unitPrice,savedCart=null){
	$(className+" .sharesAvailableCopy,"+className+" .lotteryCount").removeClass("textBold redText");
	if(syndicateInput > sharesAvailable) {
		if((savedCart != null) && (syndicateInput > 0)){
			$(className+" .sharesAvailableCopy,"+className+" .lotteryCount").addClass("textBold");
			$(className+" .sharesAvailableCopy,"+className+" .lotteryCount").addClass("redText");
			if($("#errorWithMessage").is(":hidden")){
				$("#errorWithMessage,#overlay").show();
				$("#errorWithMessage .infoWindowBody").append("<p>Oops. Seems like you selected more shares than we can give you. Someone might have already bought them.<br>Please try again.</p>");
			}
			savedCart = undefined;
		} else {
			syndicateInput = sharesAvailable;
			$(className+" .sharesAvailableCopy,"+className+" .lotteryCount").addClass("textBold");
			$(className+" .sharesAvailableCopy,"+className+" .lotteryCount").addClass("redText", {duration:500});
			$(className+" .sharesAvailableCopy,"+className+" .lotteryCount").removeClass("textBold redText", {duration:2000});
		}
	} else if(syndicateInput < 1){
		syndicateInput = 1;
	}
	
	if(syndicateInput > sharesAvailable){
		$(".syndicateBetButton").addClass('disabledState');
		$(className+" .sharesText").html("Shares");
		$(className+" .groupCountMinus").removeClass('fadeoutCounter');
		$(className+" .groupCountPlus").addClass('fadeoutCounter');
	} else if(sharesAvailable == 0){
		$(".syndicateBetButton").addClass('disabledState');
		$(className+" .groupCountMinus").addClass('fadeoutCounter');
		$(className+" .groupCountPlus").addClass('fadeoutCounter');
	} else {
		$(".syndicateBetButton").removeClass('disabledState');
		if(syndicateInput > 1){
			$(className+" .sharesText").html("Shares");
			$(className+" .groupCountMinus").removeClass('fadeoutCounter');
			if(syndicateInput >= sharesAvailable){
				$(className+" .groupCountPlus").addClass('fadeoutCounter');
			} else {
				$(className+" .groupCountPlus").removeClass('fadeoutCounter');
			}
		} else if(sharesAvailable == 1){
			$(className+" .sharesText").html("Share");
			$(className+" .groupCountPlus").addClass('fadeoutCounter');
			$(className+" .groupCountMinus").addClass('fadeoutCounter');
		} else {
			$(className+" .sharesText").html("Share");
			$(className+" .groupCountPlus").removeClass('fadeoutCounter');
			$(className+" .groupCountMinus").addClass('fadeoutCounter');
		}
	}
	$(className+" .syndicateTotalPrice").html((unitPrice * syndicateInput).toFixed(2));
	return syndicateInput;
}

    var chatOpen = false;

    $(document).ready(function() {
        if (localStorage.getItem('chatOpen') === 'true') {
            $('#chatModal').show();
            chatOpen = true;
            restoreChatSession();
        }

        $('#chatButton').on('click', function() {
            chatOpen = !chatOpen;
            if (chatOpen) {
                $('#chatModal').show();
                localStorage.setItem('chatOpen', 'true');
                restoreChatSession();
            } else {
                $('#chatModal').hide();
                localStorage.setItem('chatOpen', 'false');
            }
        });

        $('#chatClose').on('click', function() {
            $('#chatModal').hide();
            chatOpen = false;
            localStorage.setItem('chatOpen', 'false');
        });

        $('#chatEmailSubmit').on('click', function() {
            var email = $('#chatEmailInput').val().trim();
            if (email !== '') {
                setEmail(email);
            }
        });

        $('#chatSend').on('click', function() {
            sendMessage();
        });

        $('#chatInput').on('keypress', function(e) {
            if (e.which == 13) {
                sendMessage();
            }
        });
    });

    function restoreChatSession() {
        var storedEmail = localStorage.getItem('chatEmail');
        if (storedEmail) {
            $.ajax({
                url: '/resources/php_functions/live-chat-process.php',
                type: 'POST',
                data: { action: 'set_email', email: storedEmail },
                dataType: 'json',
                success: function(response) {
                    if (response.status === 'success') {
                        $('#emailPrompt').hide();
                        $('#chatMessages').show();
                        $('#chatInputArea').show();
                        fetchMessages();
                        setInterval(fetchMessages, 3000);
                    }
                }
            });
        } else {
            $('#emailPrompt').show();
            $('#chatMessages').hide();
            $('#chatInputArea').hide();
        }
    }

    function setEmail(email) {
        $.ajax({
            url: '/resources/php_functions/live-chat-process.php',
            type: 'POST',
            data: { action: 'set_email', email: email },
            dataType: 'json',
            success: function(response) {
                if (response.status === 'success') {
                    localStorage.setItem('chatEmail', email);
                    $('#emailPrompt').hide();
                    $('#chatMessages').show();
                    $('#chatInputArea').show();
                    fetchMessages();
                    setInterval(fetchMessages, 3000);
                }
            }
        });
    }

    function sendMessage() {
        var message = $('#chatInput').val().trim();
        if (message === '') return;

        $.ajax({
            url: '/resources/php_functions/live-chat-process.php',
            type: 'POST',
            data: { action: 'send_message', message: message },
            dataType: 'json',
            success: function(response) {
                if (response.status === 'success') {
                    $('#chatInput').val('');
                    fetchMessages();
                } else {
                    console.log(response);
                }
            }
        });
    }

    function fetchMessages() {
        $.ajax({
            url: '/resources/php_functions/live-chat-process.php',
            type: 'POST',
            data: { action: 'fetch_messages' },
            dataType: 'json',
            success: function(response) {
                if (response.status === 'success') {
                    var messages = response.messages;
                    var html = '';
                    for (var i = 0; i < messages.length; i++) {
                        html += '<div class="message"><span class="email">' 
                              + messages[i].email 
                              + ':</span> ' 
                              + messages[i].message 
                              + '</div>';
                    }
                    $('#chatMessages').html(html);
                    $('#chatMessages').scrollTop($('#chatMessages')[0].scrollHeight);
                }
            }
        });
    }